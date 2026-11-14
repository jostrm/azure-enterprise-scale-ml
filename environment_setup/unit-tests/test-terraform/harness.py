"""Shared helpers of the Terraform port test suite: paths, tools, Bicep evaluation and workflow replay.

Credential-free: Terraform runs `init -backend=false`, `validate` and `console` (no provider is configured,
nothing is planned against Azure); Bicep runs `build` and `build-params`. Both tools are required: a missing
tool fails the suite instead of skipping it.
"""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SUITE = Path(__file__).resolve().parent
REPO_ROOT = SUITE.parents[2]
AIFACTORY = REPO_ROOT / "environment_setup" / "aifactory"
TERRAFORM_DIR = AIFACTORY / "terraform"
ROOT_MODULE = TERRAFORM_DIR / "esml-common"
MODULES = TERRAFORM_DIR / "modules"
PARITY_MAP = TERRAFORM_DIR / "parity_map.json"
BICEP_DIR = AIFACTORY / "bicep"
BICEP_MAIN = BICEP_DIR / "esml-common" / "main"
ENTRY_FILES = ("11-rgCommon.bicep", "12-networkCommon.bicep", "13-rgLevel.bicep")
VARIABLES_JSON = AIFACTORY / "variables.json"
BICEP_WORKFLOW = BICEP_DIR / "copy_to_local_settings" / "github-actions" / "infra-common.yml"
TERRAFORM_WORKFLOW = TERRAFORM_DIR / "copy_to_local_settings" / "github-actions" / "infra-common-terraform.yml"

sys.path.insert(0, str(REPO_ROOT / "environment_setup" / "unit-tests" / "test-bicep"))
from base.arm_expressions import arm_value  # noqa: E402  (shared ARM expression evaluator)


# --------------------------------------------------------------------------------------------- tools

def tool(name: str, variable: str) -> str:
    """The executable of a required tool: $TERRAFORM / $BICEP, else PATH. Missing tools fail the test."""
    found = os.environ.get(variable) or shutil.which(name)
    assert found, f"{name} is required by the Terraform suite (set {variable} or put {name} on PATH)"
    return found


def run(arguments: list[str], cwd: Path | None = None, timeout: int = 900, stdin: str | None = None,
        environment: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, CHECKPOINT_DISABLE="1", TF_IN_AUTOMATION="1", TF_INPUT="0")
    env.update(environment or {})
    return subprocess.run(arguments, cwd=cwd, input=stdin, capture_output=True, text=True, encoding="utf-8",
                          timeout=timeout, check=False, env=env)


def terraform(*arguments: str, cwd: Path, timeout: int = 900, stdin: str | None = None) -> subprocess.CompletedProcess:
    return run([tool("terraform", "TERRAFORM"), *arguments], cwd=cwd, timeout=timeout, stdin=stdin)


def bicep(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return run([tool("bicep", "BICEP"), *arguments], cwd=cwd)


# --------------------------------------------------------------------------------------------- Bicep

def module_closure() -> dict[Path, str]:
    """Every Bicep file reached from the three entry files (module and import references)."""
    seen: dict[Path, str] = {}

    def walk(path: Path) -> None:
        path = path.resolve()
        if path in seen:
            return
        source = path.read_text(encoding="utf-8-sig")
        seen[path] = source
        for match in re.finditer(r"^\s*(?:module\s+\w+\s+'([^']+)'|import\s+.*?from\s+'([^']+)')", source, re.M):
            reference = match.group(1) or match.group(2)
            if ":" in reference:  # registry modules (br/public:...) hold types only
                continue
            walk(path.parent / reference)

    for entry in ENTRY_FILES:
        walk(BICEP_MAIN / entry)
    return seen


def deployed_resource_types() -> dict[str, list[str]]:
    """'<type>@<apiVersion>' -> Bicep files that deploy it (existing references excluded). Nested child
    resources ('resource x 'containers' = ...' inside a parent) take the parent's type and API version."""
    types: dict[str, list[str]] = {}
    declaration = re.compile(r"^\s*resource\s+\w+\s+'([^']+)'\s*(existing)?")
    for path, source in module_closure().items():
        stack: list[tuple[int, str, str]] = []  # (brace depth at declaration, full type, api version)
        depth = 0
        for line in source.splitlines():
            code = re.sub(r"//.*$", "", re.sub(r"'(?:[^'\\]|\\.)*'", "''", line))
            while stack and depth <= stack[-1][0]:
                stack.pop()
            match = declaration.match(line)
            if match:
                reference, existing = match.group(1), match.group(2)
                if "@" in reference:
                    full, version = reference.split("@", 1)
                else:
                    assert stack, f"{path}: nested resource '{reference}' outside a parent"
                    full, version = f"{stack[-1][1]}/{reference}", stack[-1][2]
                stack.append((depth, full, version))
                if not existing:
                    types.setdefault(f"{full}@{version}", []).append(path.relative_to(BICEP_DIR).as_posix())
            depth += code.count("{") - code.count("}")
    return types


@lru_cache
def compiled(entry: str, symbolic: bool = True) -> dict:
    """`bicep build` of an entry file. symbolic=True compiles with symbolic resource names (languageVersion 2.0)
    in a temporary copy of the Bicep tree, so each module keeps its Bicep symbol."""
    import tempfile

    if not symbolic:
        result = bicep("build", str(BICEP_MAIN / entry), "--stdout", "--no-restore")
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    temporary = Path(tempfile.mkdtemp(prefix="aif-tf-bicep-"))
    shutil.copytree(BICEP_DIR, temporary / "bicep")
    config_path = BICEP_DIR / "bicepconfig.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    config.setdefault("experimentalFeaturesEnabled", {})["symbolicNameCodegen"] = True
    (temporary / "bicep" / "bicepconfig.json").write_text(json.dumps(config), encoding="utf-8")
    result = bicep("build", str(temporary / "bicep" / "esml-common" / "main" / entry), "--stdout", "--no-restore")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def unique_strings_from_bicep(inputs: list[list[str]]) -> list[str]:
    """ARM's own uniqueString() of each argument list, evaluated by the Bicep compiler (build-params)."""
    import tempfile

    work = Path(tempfile.mkdtemp(prefix="aif-tf-unique-"))
    (work / "m.bicep").write_text("".join(f"param p{i} string\n" for i in range(len(inputs))), encoding="utf-8")
    lines = ["using 'm.bicep'"]
    for index, arguments in enumerate(inputs):
        quoted = ", ".join("'" + value.replace("\\", "\\\\").replace("'", "\\'").replace("${", "\\${") + "'"
                           for value in arguments)
        lines.append(f"param p{index} = uniqueString({quoted})")
    (work / "m.bicepparam").write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = bicep("build-params", str(work / "m.bicepparam"), "--stdout")
    assert result.returncode == 0, result.stderr
    parameters = json.loads(json.loads(result.stdout)["parametersJson"])["parameters"]
    return [parameters[f"p{index}"]["value"] for index in range(len(inputs))]


def unique_string(*values: str) -> str:
    """ARM uniqueString(): MurmurHash64A of the "-"-joined UTF-8 text, as 13 base32 characters.
    The test oracle; test_unique_string.py checks it against the Bicep compiler first."""
    data = "-".join(values).encode("utf-8")
    mask = 0xFFFFFFFF

    def rotl(x: int, r: int) -> int:
        return ((x << r) | (x >> (32 - r))) & mask

    length, h1, h2, index = len(data), 0, 0, 0
    while index + 7 < length:
        k1 = int.from_bytes(data[index:index + 4], "little")
        k3 = int.from_bytes(data[index + 4:index + 8], "little")
        k1 = rotl(k1 * 597399067 & mask, 15) * 2869860233 & mask
        h1 = (rotl(h1 ^ k1, 19) + h2) * 5 + 1444728091 & mask
        k3 = rotl(k3 * 2869860233 & mask, 17) * 597399067 & mask
        h2 = (rotl(h2 ^ k3, 13) + h1) * 5 + 197830471 & mask
        index += 8
    tail = length - index
    if tail > 0:
        k2 = int.from_bytes(data[index:index + min(tail, 4)], "little")
        h1 ^= rotl(k2 * 597399067 & mask, 15) * 2869860233 & mask
        if tail > 4:
            k4 = int.from_bytes(data[index + 4:index + tail], "little") * -1425107063 & mask
            h2 ^= rotl(k4, 17) * 597399067 & mask
    h1 ^= length
    h2 ^= length
    h1 = h1 + h2 & mask
    h2 = h2 + h1 & mask

    def fmix(h: int) -> int:
        h ^= h >> 16
        h = h * 2246822507 & mask
        h ^= h >> 13
        h = h * 3266489909 & mask
        return h ^ h >> 16

    h1, h2 = fmix(h1), fmix(h2)
    h1 = h1 + h2 & mask
    h2 = h2 + h1 & mask
    value = h2 << 32 | h1
    alphabet = "abcdefghijklmnopqrstuvwxyz234567"
    return "".join(alphabet[(value >> (59 - 5 * i)) & 31] if i < 12 else alphabet[(value << 1) & 31]
                   for i in range(13))


def arm_context(subscription_id: str, location: str) -> dict:
    """Deployment functions for base.arm_expressions at subscription scope (Azure public cloud)."""
    return {
        "subscription": lambda *_: {"subscriptionId": subscription_id, "id": f"/subscriptions/{subscription_id}"},
        "subscriptionResourceId": lambda *args: _subscription_resource_id(subscription_id, *args),
        "resourceId": lambda *args: _resource_id(subscription_id, *args),
        "uniqueString": unique_string,
        "environment": lambda: {"name": "AzureCloud", "suffixes": {"storage": "core.windows.net",
                                                                   "keyvaultDns": ".vault.azure.net"}},
        "deployment": lambda: {"location": location, "name": "deployment"},
        "string": lambda value: value if isinstance(value, str) else json.dumps(value),
        "last": lambda items: items[-1],
        "first": lambda items: items[0],
        "coalesce": lambda *items: next((item for item in items if item is not None), None),
        "tryGet": lambda container, *keys: _try_get(container, keys),
        "toUpper": str.upper,
        "concat": lambda *items: "".join(items) if all(isinstance(i, str) for i in items) else sum(items, []),
        "intersection": lambda *items: [x for x in items[0] if all(x in other for other in items[1:])],
        "not": lambda item: not item,
        "bool": lambda item: item if isinstance(item, bool) else str(item).lower() == "true",
        "int": int,
        "startsWith": lambda text, prefix: text.lower().startswith(prefix.lower()),
        "endsWith": lambda text, suffix: text.lower().endswith(suffix.lower()),
        "indexOf": lambda text, item: text.lower().find(item.lower()),
        "lastIndexOf": lambda text, item: text.lower().rfind(item.lower()),
        "join": lambda items, separator: separator.join(items),
    }


def _try_get(container, keys):
    for key in keys:
        try:
            container = container[key]
        except (KeyError, IndexError, TypeError):
            return None
    return container


def _type_index(parts) -> int:
    return next(index for index, part in enumerate(parts) if "/" in part and "." in part.split("/")[0])


def _subscription_resource_id(default_subscription: str, *args: str) -> str:
    parts = list(args)
    index = _type_index(parts)
    subscription = parts[0] if index == 1 else default_subscription
    resource_type, names = parts[index], parts[index + 1:]
    if resource_type.lower() == "microsoft.resources/resourcegroups":
        return f"/subscriptions/{subscription}/resourceGroups/{names[0]}"
    segments = resource_type.split("/")
    path = "/".join(f"{segment}/{name}" for segment, name in zip(segments[1:], names))
    return f"/subscriptions/{subscription}/providers/{segments[0]}/{path}"


def _resource_id(default_subscription: str, *args: str) -> str:
    parts = list(args)
    type_index = _type_index(parts)
    scope = parts[:type_index]
    subscription = scope[0] if len(scope) == 2 else default_subscription
    group = scope[-1]
    resource_type, names = parts[type_index], parts[type_index + 1:]
    if resource_type == "Microsoft.Resources/resourceGroups":
        return f"/subscriptions/{subscription}/resourceGroups/{names[0]}"
    segments = resource_type.split("/")
    path = "/".join(f"{segment}/{name}" for segment, name in zip(segments[1:], names))
    return f"/subscriptions/{subscription}/resourceGroups/{group}/providers/{segments[0]}/{path}"


def bicep_parameters(template: dict, values: dict) -> dict:
    """Parameters as ARM sees them: the given values converted to the declared types, plus the defaults."""
    merged = {}
    for name, declared in template["parameters"].items():
        kind = declared["type"].lower()
        if name in values:
            value = values[name]
            if kind == "bool" and isinstance(value, str):
                value = value.lower() == "true"
            elif kind == "int" and isinstance(value, str):
                value = int(value)
            elif kind in ("object", "array") and isinstance(value, str):
                value = json.loads(value)
            merged[name] = value
        elif "defaultValue" in declared:
            merged[name] = declared["defaultValue"]
    return merged


def bicep_conditions(entry: str, parameters: dict, subscription_id: str) -> dict[str, bool]:
    """Bicep module/resource symbol -> condition value, for every resource of the compiled entry file."""
    template = compiled(entry)
    context = arm_context(subscription_id, parameters.get("location", ""))
    values = {**parameters}
    for name, declared in template["parameters"].items():
        if name not in values and "defaultValue" in declared:
            values[name] = arm_value(declared["defaultValue"], values, template, context)
    result = {}
    for symbol, resource in template["resources"].items():
        if resource.get("existing"):
            continue
        condition = resource.get("condition", True)
        result[symbol] = bool(arm_value(condition, values, template, context))
    return result


def bicep_variable(entry: str, name: str, parameters: dict, subscription_id: str):
    template = compiled(entry)
    context = arm_context(subscription_id, parameters.get("location", ""))
    return arm_value(template["variables"][name], parameters, template, context)


# --------------------------------------------------------------------------------------------- workflow replay

def _job_section(workflow: str, job: str = "common-dev") -> str:
    match = re.search(rf"^  {job}:\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow, re.M | re.S)
    assert match, job
    return match.group(1)


def _github_expression(expression: str, github_vars: dict, secrets: dict):
    """Evaluate the small `${{ }}` subset the common job env uses: vars/secrets, ||, &&, == and !=, literals."""
    inner = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", expression.strip().strip('"'))
    assert inner, expression
    tokens = re.findall(r"vars\.\w+|secrets\.\w+|'[^']*'|\|\||&&|==|!=", inner.group(1))

    def value(token):
        if token.startswith("vars."):
            return github_vars.get(token[5:], "")
        if token.startswith("secrets."):
            return secrets.get(token[8:], "")
        return token[1:-1]

    # precedence: == / != > && > ||
    def parse_or(index):
        left, index = parse_and(index)
        while index < len(tokens) and tokens[index] == "||":
            right, index = parse_and(index + 1)
            left = left or right
        return left, index

    def parse_and(index):
        left, index = parse_cmp(index)
        while index < len(tokens) and tokens[index] == "&&":
            right, index = parse_cmp(index + 1)
            left = left and right
        return left, index

    def parse_cmp(index):
        left = value(tokens[index])
        index += 1
        if index < len(tokens) and tokens[index] in ("==", "!="):
            right = value(tokens[index + 1])
            left = (left == right) if tokens[index] == "==" else (left != right)
            index += 2
        return left, index

    result, _ = parse_or(0)
    return "" if result is False else ("true" if result is True else result)


def replay_bicep_workflow(config: dict, environment: str, runtime: dict) -> dict:
    """The --parameters each Bicep step of infra-common.yml (Dev job) passes, for a variables.json with
    use_json_config_override, as az would receive them (strings).

    `runtime` holds the GitHub secrets and variables the job reads ({"secrets": {...}, "vars": {...}}).
    Replays: job env, apply-json-config-overrides.py (same-name keys and keys bound through vars.<KEY>),
    'Initialize derived variables', and the 01/02/03 --parameters lines. Returns
    {"11-rgCommon.bicep": {...}, "12-networkCommon.bicep": {...}, "13-rgLevel.bicep": {...}, "run_networking": bool}.
    """
    workflow = BICEP_WORKFLOW.read_text(encoding="utf-8")
    job = _job_section(workflow)
    github_vars, secrets = runtime.get("vars", {}), runtime.get("secrets", {})
    env: dict[str, str] = {}
    bindings: dict[str, set[str]] = {}
    for line in job.split("    steps:")[0].splitlines():
        match = re.match(r"^\s{6}([A-Za-z_]\w*):\s+(.*)$", line)
        if not match:
            continue
        name, expression = match.groups()
        if "${{" in expression:
            if "inputs." in expression or "fromJSON" in expression:
                continue
            env[name] = _github_expression(expression, github_vars, secrets)
            for source in re.findall(r"vars\.([A-Z][A-Z0-9_]*)", expression):
                bindings.setdefault(source, set()).add(name)
        else:
            env[name] = expression.strip().strip('"')
    # apply-json-config-overrides.py (dev section for dev; stage_prod/test/prod merged for later environments)
    values = dict(config.get("dev", {}))
    if environment != "dev":
        values.update(config.get("stage_prod", {}))
        values.update(config.get(environment, {}))

    def serialize(value):
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (list, dict)):
            return json.dumps(value, separators=(",", ":"))
        return str(value)

    for key, value in values.items():
        if key in ("org-department-name", "org-department-id"):
            continue
        text = serialize(value)
        env[key] = text
        for target in sorted(bindings.get(key, set()) | bindings.get(key.upper(), set())):
            env[target] = text
    # Initialize derived variables
    env["network_env"] = runtime.get("network_env") or environment
    env["tags"] = env.get("tags") or "{}"
    env["dev_test_prod"] = environment
    steps = {
        "11-rgCommon.bicep": "01_az_bicep_common_rg",
        "12-networkCommon.bicep": "02_az_bicep_private_networking",
        "13-rgLevel.bicep": "03_az_bicep_deploy_resources",
    }
    result: dict = {}
    for entry, step in steps.items():
        block = job.split(f"- name: {step}")[1].split("\n      - name:")[0]
        parameters = {}
        for name, raw in re.findall(r"--parameters (\w+)=(.*?)\s*\\?$", block, re.M):
            text = raw.strip()
            if text.startswith("'") and text.endswith("'"):
                text = text[1:-1]
            elif text.startswith('"') and text.endswith('"'):
                text = text[1:-1]
            if re.search(r"\$(?!\{\{)", text):  # computed by the step itself: $(...) or $shellVar (adminPassword, adminVmExists)
                continue

            def substitute(match):
                expression = match.group(1).strip()
                parts = [part.strip() for part in expression.split("||")]
                for part in parts:
                    if part.startswith("env."):
                        candidate = env.get(part[4:], "")
                    else:
                        candidate = part.strip("'")
                    if candidate:
                        return candidate
                return ""

            parameters[name] = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", substitute, text)
        result[entry] = parameters
    condition = re.search(r"- name: 02_az_bicep_private_networking\n\s+if: (.*)", job).group(1)
    assert condition.strip() == "env.runNetworkingVar != 'false' && env.BYO_subnets != 'true'", condition
    result["run_networking"] = env.get("runNetworkingVar", "") != "false" and env.get("BYO_subnets", "") != "true"
    return result


# --------------------------------------------------------------------------------------------- Terraform

def copy_terraform_tree(destination: Path) -> Path:
    shutil.copytree(TERRAFORM_DIR, destination, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*",
                                                                              ".terraform.lock.hcl"))
    return destination / "esml-common"


def console(root: Path, expression: str, var_file: Path) -> object:
    """Evaluate one expression in the root module (no plan, no provider configuration) and decode its JSON."""
    result = terraform("console", "-no-color", f"-var-file={var_file}", cwd=root,
                       stdin=f"jsonencode({' '.join(expression.split())})\n")  # console reads one line
    assert result.returncode == 0, result.stderr or result.stdout
    text = result.stdout.strip().splitlines()[-1]
    return json.loads(json.loads(text))
