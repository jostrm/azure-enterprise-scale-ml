"""Offline contracts for committed pipeline configuration, not an ADO/GHA emulator.

YAML is parsed structurally; only the expression subset used by these contracts
is interpreted. Unknown syntax fails closed. No shell, CLI, credentials or HTTP
are used. Azure template expansion and runtime service behaviour remain outside
this unit-test boundary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml

from base.config import CLS


GHA_PHASE = CLS / "github-actions" / "infra-project-phase.yml"
GHA_PROJECT = CLS / "github-actions" / "infra-project.yml"
GHA_COMMON = CLS / "github-actions" / "infra-common.yml"
GHA_GATEWAY = CLS / "github-actions" / "infra-ai-gateway.yml"
ADO_ROOT = CLS / "azure-devops" / "esml-yaml-pipelines"
ADO_PROJECT = ADO_ROOT / "esml-infra-project" / "infra-project-genai.yaml"
ADO_SERVICES = ADO_ROOT / "esml-infra-project" / "jobs" / "job-2-genai-services.yaml"
ADO_COMMON = ADO_ROOT / "esml-infra-common" / "jobs" / "job-1-aif-cmn.yaml"
ADO_GATEWAY = ADO_ROOT / "esml-infra-common" / "jobs" / "job-2-ai-gateway.yaml"

# Explicit inventory: adding/removing a public flag requires a reviewed contract.
FEATURES = dict(
    line.split()
    for line in """
ENABLE_AMPLS enableAMPLS
ENABLE_ADMIN_VM enableAdminVM
ENABLE_AI_FACTORY_HUB enableAIFactoryHub
ENABLE_PUBLIC_GENAI_ACCESS enablePublicGenAIAccess
ENABLE_PUBLIC_ACCESS_WITH_PERIMETER enablePublicAccessWithPerimeter
ENABLE_APIM ENABLE_APIM
ENABLE_KONG ENABLE_KONG
ENABLE_DEFENDER_FOR_AI_SUB_LEVEL enableDefenderforAISubLevel
ENABLE_DEFENDER_FOR_AI_RESOURCE_LEVEL enableDefenderforAIResourceLevel
ENABLE_DELETE_FOR_DISABLED_RESOURCES enableDeleteForDisabledResources
ENABLE_AI_FOUNDRY enableAIFoundry
ENABLE_FOUNDRY_CAPHOST enableAFoundryCaphost
ENABLE_AIFACTORY_CREATED_DEFAULT_PROJECT_FOR_AIFV2 enableAIFactoryCreatedDefaultProjectForAIFv2
ENABLE_DATAFACTORY enableDatafactory
ENABLE_DATAFACTORY_COMMON enableDatafactoryCommon
ENABLE_AZURE_MACHINE_LEARNING enableAzureMachineLearning
ENABLE_AKS_FOR_AZURE_ML enableAksForAzureML
ENABLE_AKS enableAKS
ENABLE_DATABRICKS enableDatabricks
ENABLE_AI_SEARCH enableAISearch
ENABLE_AI_SEARCH_SHARED_PRIVATE_LINK enableAISearchSharedPrivateLink
ENABLE_AZURE_OPENAI enableAzureOpenAI
ENABLE_AZURE_AI_VISION enableAzureAIVision
ENABLE_AZURE_SPEECH enableAzureSpeech
ENABLE_AI_DOC_INTELLIGENCE enableAIDocIntelligence
ENABLE_BING enableBing
ENABLE_BING_CUSTOM_SEARCH enableBingCustomSearch
ENABLE_CONTENT_SAFETY enableContentSafety
ENABLE_COSMOS_DB enableCosmosDB
ENABLE_POSTGRESQL enablePostgreSQL
ENABLE_REDIS_CACHE enableRedisCache
ENABLE_SQL_DATABASE enableSQLDatabase
ENABLE_ELASTICSEARCH enableElasticsearch
ENABLE_FUNCTION enableFunction
ENABLE_WEBAPP enableWebApp
ENABLE_CONTAINER_APPS enableContainerApps
ENABLE_AZURE_MCP_SERVER enableAzureMcpServer
ENABLE_APPINSIGHTS_DASHBOARD enableAppInsightsDashboard
ENABLE_APPLICATION_INSIGHTS enableApplicationInsights
ENABLE_LOGIC_APPS enableLogicApps
ENABLE_EVENT_HUBS enableEventHubs
ENABLE_BOT_SERVICE enableBotService
ENABLE_RETRIES enableRetries
ENABLE_AI_SERVICES enableAIServices
ENABLE_AI_FOUNDRY_HUB enableAIFoundryHub
""".strip().splitlines()
)

# These flags are inventoried/default-checked, NOT claimed as deployable services.
CONFIG_ONLY_EXCEPTIONS = {
    "ENABLE_AI_FACTORY_HUB": "Explicit configuration-only Hub intent; the templates promise no deployment.",
    "ENABLE_AMPLS": "Legacy Hub switch has no GHA common/project binding; known wiring gap, not covered as a deployable flag.",
    "ENABLE_RETRIES": "Legacy retry setting is not forwarded by GHA; task/script retry policy is outside service provisioning.",
}
DEFAULT_EXCEPTIONS = {
    "ENABLE_AKS_FOR_AZURE_ML": (
        "true", "false",
        "Existing GHA example enables AML inference AKS while ADO opts out; preserve deployment defaults and test explicit overrides.",
    ),
}
GATEWAY_FLAGS = {"ENABLE_APIM", "ENABLE_KONG"}
COMMON_FLAGS = {"ENABLE_ADMIN_VM", "ENABLE_DATAFACTORY_COMMON"}

PUBLIC_FLAGS = "enablePublicGenAIAccess enablePublicAccessWithPerimeter"
MODULE_FLAGS = {
    "02-core-infrastructure.bicep": PUBLIC_FLAGS + " enableApplicationInsights enableLogicApps",
    "03-cognitive-services.bicep": PUBLIC_FLAGS + " enableAIServices enableAISearch enableAzureOpenAI enableContentSafety enableAzureAIVision enableAzureSpeech enableAIDocIntelligence enableBingCustomSearch enableBing enableAFoundryCaphost enableAIFoundry enableAISearchSharedPrivateLink",
    "04-databases.bicep": PUBLIC_FLAGS + " enableCosmosDB enablePostgreSQL enableRedisCache enableSQLDatabase enableElasticsearch enableAFoundryCaphost enableAIFoundry",
    "05-compute-services.bicep": PUBLIC_FLAGS + " enableContainerApps enableFunction enableWebApp enableBingSearch enableAzureOpenAI enableAISearch enableAIServices enableAppInsightsDashboard enableAIFoundry enableAKS",
    "06-ai-platform.bicep": PUBLIC_FLAGS + " enableAIFoundryHub enableAISearch enableAIServices",
    "07-ml-data-platform.bicep": "enablePublicAccessWithPerimeter enableDatafactory enableAzureMachineLearning enableDatabricks enableAksForAzureML",
    "11-integration.bicep": "enablePublicAccessWithPerimeter enableLogicApps enableEventHubs enableFunction enableWebApp enableBotService",
    "09-ai-foundry-2025-v4.bicep": PUBLIC_FLAGS + " enableAISearch enableCosmosDB enableAIFactoryCreatedDefaultProjectForAIFv2 enableCaphost enableAIFoundry enableDefenderforAISubLevel enableDefenderforAIResourceLevel",
}
COMMON_MODULE_FLAGS = {
    "11-rgCommon.bicep": "enableAdminVM enableDefenderforAISubLevel enableDefenderforAIResourceLevel",
    "13-rgLevel.bicep": "enableAdminVM enablePublicAccessWithPerimeter enableDatafactoryCommon",
}
PARAMETER_ALIASES = {"enableBingSearch": "enableBing", "enableCaphost": "enableAFoundryCaphost"}


def load_pipeline(path: Path) -> dict:
    # BaseLoader preserves "on" and boolean-looking strings without YAML 1.1 coercion.
    class UniqueLoader(yaml.BaseLoader):
        pass

    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if key in result:
                raise AssertionError(f"{path.name}: duplicate YAML key {key}")
            result[key] = loader.construct_object(value_node)
        return result

    UniqueLoader.add_constructor("tag:yaml.org,2002:map", mapping)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)


def inventory_errors(env: dict, ado: dict) -> list[str]:
    errors = []
    for label, values, expected in ((".env.template", env, set(FEATURES)),
                                     ("variables.yaml", ado, set(FEATURES.values()))):
        actual = {key for key in values if key.lower().startswith("enable")}
        if actual != expected:
            errors.append(f"{label}: uncontracted={sorted(actual - expected)}, missing={sorted(expected - actual)}")
    for public, runtime in FEATURES.items():
        for label, values, key in (("GHA", env, public), ("ADO", ado, runtime)):
            if key in values and values[key] not in ("true", "false"):
                errors.append(f"{label} {key}: expected canonical boolean string, got {values[key]!r}")
        if public in DEFAULT_EXCEPTIONS and public in env and runtime in ado:
            expected = DEFAULT_EXCEPTIONS[public][:2]
            if (env[public], ado[runtime]) != expected:
                errors.append(f"{public}: default exception is stale; expected {expected!r}")
        elif public in env and runtime in ado and env[public] != ado[runtime]:
            errors.append(f"{public}/{runtime}: default mismatch {env[public]!r} != {ado[runtime]!r}")
    return errors


def objects(value: Any) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


@dataclass
class Deployment:
    name: str
    module: str
    parameters: dict[str, str]
    step: dict


def deployments(pipeline: dict) -> list[Deployment]:
    result = []
    for step in objects(pipeline):
        script = step.get("run", step.get("inputs", {}).get("inlineScript", ""))
        if not isinstance(script, str):
            continue
        script = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
        templates = re.findall(r'--template-file\s+"([^"]+\.bicep)"', script)
        if not templates or not re.search(r"\baz deployment (?:sub|group) create\b", script):
            continue
        if len(templates) != 1:
            raise AssertionError("Multiple deployment templates in one step require an explicit contract")
        parameters = {}
        for match in re.finditer(r"""--parameters\s+(\w+)=(?:"([^"]*)"|'([^']*)'|([^\s\\]+))""", script):
            name = match[1]
            value = next(value for value in match.groups()[1:] if value is not None)
            if name in parameters and parameters[name] != value:
                raise AssertionError(f"{step.get('name', step.get('displayName'))}: conflicting parameter {name}")
            parameters[name] = value
        result.append(Deployment(
            step.get("name", step.get("displayName", "")),
            templates[0].replace("\\", "/").rsplit("/", 1)[-1],
            parameters, step,
        ))
    return result


def forwarding_errors(pipeline: dict, platform: str, required: dict[str, str] = MODULE_FLAGS) -> list[str]:
    found = deployments(pipeline)
    errors = []
    for module, flags in required.items():
        matches = [deployment for deployment in found if deployment.module == module]
        if not matches:
            errors.append(f"{platform}: missing deployment of {module}")
        for deployment in matches:
            for parameter in flags.split():
                source = PARAMETER_ALIASES.get(parameter, parameter)
                expected = f"$({source})" if platform == "ado" else "${{ env." + source + " }}"
                actual = deployment.parameters.get(parameter)
                if actual != expected:
                    errors.append(f"{platform}/{deployment.name}: {parameter} must forward {source}; got {actual!r}")
    return errors


_TOKEN = re.compile(r"\s*(?:('(?:[^']|'')*')|([A-Za-z_][\w.-]*)|(&&|\|\||==|!=|[(),\[\]]))")


def evaluate(expression: str, context: dict[str, Any]) -> Any:
    """Interpret our bounded CI expression grammar without eval or subprocesses."""
    expression = expression.strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip()
    # ADO substitutes these parameters before evaluating runtime conditions.
    expression = re.sub(
        r"'\$\{\{\s*parameters\.(\w+)\s*\}\}'",
        lambda match: "'" + str(context["parameters." + match[1]]) + "'",
        expression,
    )
    tokens, position = [], 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if not match:
            if not expression[position:].strip():
                break
            raise AssertionError(f"Unsupported CI expression syntax: {expression[position:]}")
        tokens.append(next(part for part in match.groups() if part is not None))
        position = match.end()
    index = 0

    def consume(expected=None):
        nonlocal index
        if index >= len(tokens):
            raise AssertionError(f"Incomplete CI expression: {expression}")
        token = tokens[index]
        if expected is not None and token != expected:
            raise AssertionError(f"Expected {expected}, got {token}: {expression}")
        index += 1
        return token

    def peek():
        return tokens[index] if index < len(tokens) else None

    def equal(left, right):
        # CI string comparisons are case-insensitive; string "false" is not false.
        if isinstance(left, str) and isinstance(right, str):
            return left.lower() == right.lower()
        return type(left) is type(right) and left == right

    def atom():
        token = consume()
        if token == "(":
            value = logical_or()
            consume(")")
            return value
        if token.startswith("'"):
            return token[1:-1].replace("''", "'")
        if token in ("true", "false"):
            return token == "true"
        if peek() == "(":
            consume("(")
            args = []
            while peek() != ")":
                args.append(logical_or())
                if peek() != ",":
                    break
                consume(",")
            consume(")")
            functions = {
                "and": lambda *items: all(items), "or": lambda *items: any(items),
                "not": lambda item: not item, "eq": equal,
                "ne": lambda left, right: not equal(left, right),
                "in": lambda item, *items: any(equal(item, other) for other in items),
                "success": lambda: context.get("success", True),
                "succeeded": lambda: context.get("success", True),
                "failed": lambda: context.get("failed", False),
                "canceled": lambda: context.get("canceled", False),
            }
            if token not in functions:
                raise AssertionError(f"Unsupported CI function: {token}")
            return functions[token](*args)
        if peek() == "[":
            consume("[")
            key = consume()
            if not key.startswith("'"):
                raise AssertionError(f"Expected quoted lookup: {expression}")
            consume("]")
            token += "." + key[1:-1]
        if token not in context:
            raise AssertionError(f"Missing expression input: {token}")
        return context[token]

    def comparison():
        left = atom()
        while peek() in ("==", "!="):
            operator = consume()
            right = atom()
            left = equal(left, right) if operator == "==" else not equal(left, right)
        return left

    def logical_and():
        left = comparison()
        while peek() == "&&":
            consume()
            right = comparison()
            left = right if left else left
        return left

    def logical_or():
        left = logical_and()
        while peek() == "||":
            consume()
            right = logical_and()
            left = left if left else right
        return left

    result = logical_or()
    if index != len(tokens):
        raise AssertionError(f"Unconsumed CI expression: {expression}")
    return result
