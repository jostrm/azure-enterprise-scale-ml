"""Local Graphify extraction plus conservative Azure/source-contract adapters."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import fnmatch
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile

import yaml

ROOTS = (
    "00-start.sh", "01-start-v125-and-above.sh",
    ".github", "bootstrap", "environment_setup", "copy_my_subfolders_to_my_grandparent",
    "esml", "esml-v2", "esmlfac", "esmlrt", "healthmodel", "usecase_code", "mcp",
)
EXTENSIONS = {".py", ".sh", ".ps1", ".bicep", ".bicepparam", ".yml", ".yaml", ".json", ".ipynb", ".toml", ".txt"}
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache",
    "node_modules", "site-packages", "vendor", "dist", "build", "out", "outputs",
    "artifacts", "data", "datasets", "models", "mlruns", "logs", "journals",
    "operation-store", "operations-store", "aa_ref_code", ".obsidian",
}
JSON_ALLOWLIST = (
    "*.schema.json", "*/schemas/*.json", "*/schema/*.json", "*.example.json",
    "*/examples/*.json", "*/parameters.example.json", "*/tool-contracts.json",
    "*/evaluations.json", "*/package.json", "*/release-manifest.json",
    "usecase_code/50-ml-model-factory/user-config/model/scenarios/*.json",
    "usecase_code/50-ml-model-factory/user-config/model/model-selection.json",
    "usecase_code/50-ml-model-factory/user-config/databricks/job-template.json",
    "environment_setup/aifactory/variables.json",
)
MAX_FILE_BYTES = 2_000_000
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{30,})\b|"
    r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|"
    r"(?i:AccountKey=[A-Za-z0-9+/]{30,}={0,2}|[?&]sig=[A-Za-z0-9%+/]{25,})"
)
FILE_LITERAL = re.compile(
    r"""["']((?:[\w.@${}() -]+[\\/])*[\w.@${}()-]+\.(?:py|sh|ps1|bicep|bicepparam|yaml|yml|json|ipynb))["']"""
)
LIMITATIONS = [
    "Static evidence is incomplete: missing edges never establish absence of a dependency.",
    "Bicep adapter is lexical, not the Azure compiler: dynamic module paths, comprehensions and runtime resource IDs may be unresolved.",
    "Workflow templates and conditions are preserved as declarations, not evaluated; retries/recovery are not flattened into a DAG.",
    "Python reflection, runtime DI bindings, dynamically assembled paths and calls require source inspection.",
    "Notebook code cells are inspected without execution; outputs, markdown cells and metadata are excluded.",
    "Configuration values and customer data are not indexed; only explicitly allowlisted configuration key contracts are extracted.",
    "Graphify static resolver inferred edges remain inferred; file-level mappings do not claim symbol-level completeness.",
    "The developer graph may include tests; it is not the approved production Search corpus or evidence of live state.",
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def notebook_code(text):
    value = json.loads(text)
    return [{"cell": index, "source": "".join(cell.get("source", []))}
            for index, cell in enumerate(value.get("cells", []), 1)
            if cell.get("cell_type") == "code"]


def input_digest(path, content):
    raw = path.read_bytes()
    current = raw.decode("utf-8-sig")
    if path.suffix == ".ipynb":
        current = canonical(notebook_code(current))
    if current != content:
        raise RuntimeError(f"Indexed input changed during generation: {path.name}")
    return digest(content if path.suffix == ".ipynb" else raw)


def blocked_path(path):
    parts = PurePosixPath(path).parts
    return any(
        part.casefold() in EXCLUDED_DIRS
        or (part.startswith(".") and part != ".github")
        or part.casefold().startswith(("venv-", "venv_", ".venv", ".workload-test"))
        or part.casefold().endswith((".egg-info", ".dist-info"))
        for part in parts
    ) or any(token in parts[-1].casefold() for token in (".local.", "credential", "private-settings"))


def select_inputs(root):
    root = Path(root).resolve()
    selected, excluded = {}, []
    for top in ROOTS:
        base = root / top
        if not base.exists() or base.is_symlink() or base.is_junction():
            continue
        entries = [(base.parent, [], [base.name])] if base.is_file() else os.walk(base, followlinks=False)
        for directory, dirs, files in entries:
            parent = Path(directory)
            kept = []
            for name in sorted(dirs):
                child = parent / name
                relative = child.relative_to(root).as_posix()
                if blocked_path(relative) or child.is_symlink() or child.is_junction():
                    excluded.append({"path": relative, "reason": "excluded_directory"})
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(files):
                file = parent / name
                relative = file.relative_to(root).as_posix()
                reason = None
                if blocked_path(relative) or file.suffix.casefold() not in EXTENSIONS:
                    reason = "excluded_path_or_type"
                elif file.is_symlink() or getattr(file.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                    reason = "reparse_or_symlink"
                elif file.suffix.casefold() == ".json" and not any(fnmatch.fnmatchcase(relative, pattern) for pattern in JSON_ALLOWLIST):
                    reason = "json_not_allowlisted"
                elif file.suffix.casefold() == ".txt" and not name.startswith("requirements"):
                    reason = "text_not_allowlisted"
                elif file.stat().st_size > MAX_FILE_BYTES:
                    reason = "oversize"
                if reason:
                    excluded.append({"path": relative, "reason": reason})
                    continue
                try:
                    content = file.read_bytes().decode("utf-8-sig")
                    if file.suffix == ".ipynb":
                        content = canonical(notebook_code(content))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    excluded.append({"path": relative, "reason": type(exc).__name__})
                    continue
                if SECRET.search(content):
                    excluded.append({"path": relative, "reason": "credential_marker"})
                    continue
                selected[relative] = content
    return dict(sorted(selected.items())), sorted(excluded, key=lambda item: item["path"])


def ownership(path):
    if path.startswith("copy_my_subfolders_to_my_grandparent/") or "/copy_to_local_settings/" in path:
        return "consumer_template"
    if path.startswith("usecase_code/50-ml-model-factory/usecase-type/"):
        return "generated_example"
    if "/user-config/" in path or path.endswith(".example.json"):
        return "user_editable_example"
    if "/_legacy/" in path or path.startswith("esml/z/"):
        return "historical_reference"
    return "accelerator"


class Builder:
    def __init__(self, inputs):
        self.inputs = inputs
        self.nodes, self.edges = {}, {}
        self.failures, self.unsupported = [], []

    def node(self, identifier, label, kind, source, line=None, **attributes):
        value = {"id": identifier, "label": label, "kind": kind, "source_file": source,
                 "file_type": Path(source).suffix.lstrip(".") or "code",
                 "evidence": "static", "resolution": "resolved", "ownership": ownership(source),
                 "ownership_evidence": "documentation/architecture/architecture/Repository-Boundaries.md"}
        if line is not None:
            value["line"] = line
        value.update(attributes)
        existing = self.nodes.setdefault(identifier, value)
        if line is not None:
            existing["line"] = line
        if value["resolution"] == "resolved":
            existing["resolution"] = "resolved"
        return identifier

    def edge(self, source, relation, target, path, line=None, **attributes):
        value = {"source": source, "target": target, "relation": relation,
                 "evidence": "static", "resolution": "resolved", "source_file": path}
        if line is not None:
            value["line"] = line
        value.update(attributes)
        self.edges[canonical(value)] = value

    def reference(self, source, reference, path, relation="references_file", line=None):
        reference = reference.replace("\\", "/")
        if reference.startswith(("/", "http:", "https:")) or ":" in reference:
            candidates = []
        else:
            candidates = [str(PurePosixPath(path).parent / reference), reference]
            candidates = [os.path.normpath(p).replace("\\", "/") for p in candidates]
        target = next((candidate for candidate in candidates if candidate in self.inputs), None)
        if target is not None:
            self.edge(source, relation, target, path, line)
            return target
        # Runtime variables and external repositories stay explicit boundaries.
        identifier = "unresolved:" + digest(path + "\0" + reference)[:24]
        self.node(identifier, reference[:200], "reference", path, line,
                  resolution="unresolved", boundary="external_or_dynamic")
        self.edge(source, relation, identifier, path, line, resolution="unresolved")
        return None

    def file_references(self, path, text, source=None, cell=None):
        source = source or path
        for match in FILE_LITERAL.finditer(text):
            self.reference(source, match.group(1), path, line=text.count("\n", 0, match.start()) + 1)
        if Path(path).suffix in {".sh", ".ps1", ".yml", ".yaml"}:
            for match in re.finditer(r"(?:--template-file|--parameters\s+@?|python(?:3)?|bash|pwsh|source|\.\/)\s+[\"']?([\w./\\-]+\.(?:py|sh|ps1|bicep|json))", text):
                self.reference(source, match.group(1), path, "invokes", text.count("\n", 0, match.start()) + 1)

    def bicep(self, path, text):
        # Remove comments but retain line positions and literals for module paths.
        text = re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
        declarations = list(re.finditer(r"(?m)^[ \t]*(param|var|resource|module|output)\s+([A-Za-z_]\w*)\b", text))
        symbols = {}
        for match in declarations:
            kind, name = match.groups()
            identifier = self.node(f"{path}::{kind}:{name}", name, kind, path, text.count("\n", 0, match.start()) + 1)
            symbols[name] = identifier
            self.edge(path, "contains", identifier, path)
        for index, match in enumerate(declarations):
            kind, name = match.groups()
            body = text[match.end():declarations[index + 1].start() if index + 1 < len(declarations) else len(text)]
            source = symbols[name]
            if kind == "module":
                module = re.match(r"\s*'([^']+)'", body)
                if module:
                    target = self.reference(source, module.group(1), path, "module_source", self.nodes[source]["line"])
                    if target:
                        for binding in re.finditer(r"(?m)([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)\b", body):
                            key, value = binding.groups()
                            if value in symbols and re.search(rf"(?m)^\s*param\s+{re.escape(key)}\b", self.inputs[target]):
                                parameter = self.node(f"{target}::param:{key}", key, "param", target)
                                self.edge(source, "passes_parameter", parameter, path)
                                self.edge(parameter, "bound_from", symbols[value], path)
            literals_removed = re.sub(r"'(?:''|[^'])*'",
                                      lambda value: " ".join(re.findall(r"\$\{([^{}]+)\}", value.group())), body)
            references = {match.group() for match in re.finditer(r"\b[A-Za-z_]\w*\b", literals_removed)
                          if not re.match(r"\s*:", literals_removed[match.end():])}
            for reference in sorted(references & symbols.keys()):
                if reference != name:
                    self.edge(source, "references", symbols[reference], path, self.nodes[source]["line"])
            depends = re.search(r"\bdependsOn\s*:\s*\[([^\]]*)\]", literals_removed, re.S)
            if depends:
                for reference in sorted(set(re.findall(r"\b\w+\b", depends.group(1))) & symbols.keys()):
                    self.edge(source, "depends_on", symbols[reference], path, self.nodes[source]["line"])
            if re.search(r"\b(?:for|if)\s*[\[(]", literals_removed):
                self.nodes[source]["conditional"] = True
                self.unsupported.append({"path": path, "construct": "conditional_or_loop_declaration", "symbol": name})
        self.file_references(path, text)

    def workflow(self, path, text):
        if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(text)):
            self.unsupported.append({"path": path, "construct": "yaml_alias"})
            return
        data = yaml.safe_load(text)
        if not isinstance(data, (dict, list)):
            return
        by_kind = {}

        def visit(value, parent=path, scope="", level=0):
            if level > 60:
                raise ValueError("YAML nesting exceeds extraction limit")
            if isinstance(value, list):
                for item in value:
                    visit(item, parent, scope, level + 1)
                return
            if not isinstance(value, dict):
                return
            selected = next(((kind, value[kind]) for kind in ("stage", "job", "deployment", "task_key")
                             if isinstance(value.get(kind), str)), None)
            if selected:
                kind, name = selected
                kind = "job" if kind in {"deployment", "task_key"} else kind
                label = (scope + "/" if scope else "") + name
                identifier = f"{path}::{kind}:{label}"
                self.node(identifier, name, kind, path,
                          conditional="condition" in value or "if" in value,
                          topology="declared_workflow")
                condition = value.get("condition", value.get("if"))
                if isinstance(condition, str):
                    self.nodes[identifier]["condition"] = condition[:1000]
                declared = re.search(rf"(?m)^[ \t-]*(?:{kind}|deployment)\s*:\s*{re.escape(name)}\s*$", text)
                if declared:
                    self.nodes[identifier]["line"] = text.count("\n", 0, declared.start()) + 1
                self.edge(parent, "contains", identifier, path)
                by_kind[(kind, label)] = identifier
                dependencies = value.get("needs", value.get("dependsOn", value.get("depends_on", [])))
                if isinstance(dependencies, str):
                    dependencies = [dependencies]
                if isinstance(dependencies, list):
                    for dependency in dependencies:
                        dependency = dependency.get("task_key") if isinstance(dependency, dict) else dependency
                        if isinstance(dependency, str):
                            target = f"{path}::{kind}:{scope + '/' if scope else ''}{dependency}"
                            self.edge(identifier, "depends_on", target, path)
                parent = identifier
                if kind == "stage":
                    scope = label
            jobs = value.get("jobs")
            if isinstance(jobs, dict):
                for name, job in jobs.items():
                    if isinstance(job, dict):
                        visit(dict(job, job=str(name)), parent, scope, level + 1)
            template = value.get("template")
            if isinstance(template, str):
                target = self.reference(parent, template, path, "template")
                parameters = value.get("parameters", {})
                if target and isinstance(parameters, dict):
                    for parameter in parameters:
                        if isinstance(parameter, str):
                            node = self.node(f"{target}::parameter:{parameter}", parameter, "parameter", target,
                                             resolution="unresolved")
                            self.edge(parent, "passes_parameter", node, path, resolution="unresolved")
            for key, item in value.items():
                if key == "jobs" and isinstance(item, dict):
                    continue
                if isinstance(item, str):
                    self.file_references(path, item, parent)
                    if "${{" in item or "$(" in item:
                        self.nodes[parent]["conditional"] = True
                elif isinstance(item, (dict, list)):
                    visit(item, parent, scope, level + 1)

        visit(data)
        for edge in tuple(self.edges.values()):
            if edge["source_file"] == path and edge["target"] not in self.nodes:
                self.node(edge["target"], edge["target"].rsplit(":", 1)[-1], "reference", path,
                          resolution="unresolved")
                edge["resolution"] = "unresolved"

    def configuration(self, path, text):
        data = json.loads(text)

        def visit(value, keys=(), depth=0):
            if depth > 50:
                raise ValueError("JSON nesting exceeds extraction limit")
            if isinstance(value, dict):
                properties = value.get("properties")
                if isinstance(properties, dict):
                    visit(properties, keys, depth + 1)
                    return
                for key, child in value.items():
                    if not isinstance(key, str):
                        continue
                    names = (*keys, key)
                    label = ".".join(names)
                    identifier = self.node(f"{path}::config:{label}", label, "config_key", path)
                    self.edge(path, "defines_config", identifier, path)
                    if isinstance(child, dict):
                        if isinstance(child.get("type"), str):
                            self.nodes[identifier]["value_type"] = child["type"][:40]
                        if "default" in child:
                            self.nodes[identifier]["has_default"] = True
                        if "properties" in child or "type" not in child:
                            visit(child, names, depth + 1)
                    elif isinstance(child, list):
                        for item in child:
                            if isinstance(item, dict):
                                visit(item, (*names, "[]"), depth + 1)
            elif isinstance(value, list):
                for child in value:
                    visit(child, (*keys, "[]"), depth + 1)
        visit(data)
        if isinstance(data, dict) and "tasks" in data:
            self.workflow(path, text)
        self.file_references(path, text)

    def python(self, path, text, *, cell=None):
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            self.unsupported.append({"path": path, "construct": "python_syntax_or_notebook_magic",
                                     "line": exc.lineno, "cell": cell})
            self.file_references(path, text)
            return
        imports = {}
        for item in ast.walk(tree):
            if isinstance(item, ast.ImportFrom) and item.level:
                parent = PurePosixPath(path).parent
                for _ in range(item.level - 1):
                    parent = parent.parent
                module = str(parent / ((item.module or "").replace(".", "/") + ".py"))
                if module in self.inputs:
                    for alias in item.names:
                        imports[alias.asname or alias.name] = (module, alias.name)

        def symbols(parent, scope=""):
            for item in ast.iter_child_nodes(parent):
                child_scope = scope
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    kind = "class" if isinstance(item, ast.ClassDef) else "function"
                    qualified = f"{scope}.{item.name}" if scope else item.name
                    identifier = f"{path}::{kind}:{qualified}" + (f":cell{cell}" if cell else "")
                    self.node(identifier, qualified, kind, path, item.lineno, **({"cell": cell} if cell else {}))
                    self.edge(path, "contains", identifier, path, item.lineno)
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        arguments = (*item.args.posonlyargs, *item.args.args, *item.args.kwonlyargs)
                        for argument in arguments:
                            if argument.annotation is None:
                                continue
                            for annotation in ast.walk(argument.annotation):
                                if isinstance(annotation, ast.Name) and annotation.id in imports:
                                    module, name = imports[annotation.id]
                                    declaration = re.search(rf"(?m)^class\s+{re.escape(name)}\s*(\([^)]*\))?:", self.inputs[module])
                                    if declaration:
                                        target = self.node(f"{module}::class:{name}", name, "class", module,
                                                           self.inputs[module].count("\n", 0, declaration.start()) + 1)
                                        relation = "uses_interface" if "Protocol" in (declaration.group(1) or "") else "annotated_as"
                                        self.edge(identifier, relation, target, path, argument.lineno)
                    child_scope = qualified
                symbols(item, child_scope)
        symbols(tree)
        self.file_references(path, text)
        if cell is not None and "/usecase-type/" in path:
            base = path.split("/usecase-type/", 1)[0]
            for generator in ("examples.py", "usecases.py"):
                source = f"{base}/accelerator/src/ml_model_factory/{generator}"
                if source in self.inputs and "SCENARIO" in text:
                    self.edge(path, "generated_from", source, path, evidence="explicit", cell=cell)
            scenario = re.search(r'SCENARIO\s*=\s*ROOT\s*/\s*["\']user-config["\']\s*/\s*["\']model["\']\s*/\s*["\']scenarios["\']\s*/\s*["\']([^"\']+)["\']', text)
            if scenario:
                target = f"{base}/user-config/model/scenarios/{scenario.group(1)}"
                if target in self.inputs:
                    self.edge(path, "configured_by", target, path, cell=cell)

    def build(self):
        for path in self.inputs:
            self.node(path, PurePosixPath(path).name, "file", path)
        for path, text in self.inputs.items():
            suffix = Path(path).suffix.casefold()
            try:
                if suffix in {".bicep", ".bicepparam"}:
                    self.bicep(path, text)
                elif suffix in {".yml", ".yaml"}:
                    self.workflow(path, text)
                elif suffix == ".json":
                    self.configuration(path, text)
                elif suffix == ".py":
                    self.python(path, text)
                elif suffix == ".ipynb":
                    for cell in json.loads(text):
                        self.python(path, cell["source"], cell=cell["cell"])
                else:
                    self.file_references(path, text)
            except (ValueError, yaml.YAMLError, RecursionError) as exc:
                self.failures.append({"path": path, "error": type(exc).__name__})
        graph = {"directed": True, "multigraph": True, "graph": {"schema_version": 1},
                 "nodes": sorted(self.nodes.values(), key=lambda item: item["id"]),
                 "links": sorted(self.edges.values(), key=canonical)}
        return graph, {
            "indexed_files": len(self.inputs), "by_extension": dict(sorted(Counter(Path(p).suffix for p in self.inputs).items())),
            "extraction_failures": self.failures, "unsupported_constructs": self.unsupported,
            "unresolved_references": sum(e["resolution"] == "unresolved" for e in graph["links"]),
            "inferred_edges": sum(e["evidence"] == "inferred" for e in graph["links"]),
            "limitations": LIMITATIONS,
        }


def extract_adapters(root):
    inputs, excluded = select_inputs(root)
    graph, report = Builder(inputs).build()
    report["excluded_counts"] = dict(sorted(Counter(item["reason"] for item in excluded).items()))
    return graph, report


def selection_metadata(excluded):
    return {
        # Fixed root entry points are hash-checked inputs, not directory inventories.
        "roots": [*[root for root in ROOTS if not root.endswith(".sh")], "documentation/architecture"],
        "extensions": sorted(EXTENSIONS | {".md"}),
        "exclude_dirs": sorted(EXCLUDED_DIRS),
        "exclude_globs": [
            "**/.*/**", "**/.venv*", "**/.workload-test*", "**/*.local.*",
            "**/venv-*", "**/venv_*", "**/*.egg-info/*", "**/*.dist-info/*",
            "**/*credential*", "**/*private-settings*",
            *[item["path"] for item in excluded
              if item["reason"] not in {"excluded_path_or_type", "json_not_allowlisted", "text_not_allowlisted"}],
        ],
        "include_globs": [
            *["*" + suffix for suffix in sorted(EXTENSIONS - {".json", ".txt"})],
            *JSON_ALLOWLIST, "**/requirements*.txt",
            "documentation/architecture/*.md", "documentation/architecture/**/*.md",
        ],
        "max_file_bytes": MAX_FILE_BYTES,
    }


def graphify_commands(stage, out):
    return [
        ["extract", str(stage), "--code-only", "--no-dedup", "--no-cluster", "--out", str(out)],
        ["cluster-only", str(out), "--no-label"],
    ]


def run_graphify(arguments, cwd):
    env = dict(os.environ)
    env.update(GRAPHIFY_OUT="graphify-out", GRAPHIFY_GOOGLE_WORKSPACE="0",
               GRAPHIFY_QUERY_LOG_DISABLE="1", GRAPHIFY_NO_AUTO_REFRESH="1",
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0")
    runner = Path(__file__).with_name("static_runner.py")
    result = subprocess.run([sys.executable, str(runner), *arguments], cwd=cwd, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    result.check_returncode()
    return result.stdout + result.stderr


def html_projection(graph):
    groups = sorted({PurePosixPath(node["source_file"]).parts[0] for node in graph["nodes"]})
    identifiers = {group: index for index, group in enumerate(groups)}
    view = dict(graph, nodes=[dict(node, community=identifiers[PurePosixPath(node["source_file"]).parts[0]])
                              for node in graph["nodes"]])
    return view, {str(index): group for group, index in identifiers.items()}


def merge_upstream(graph, upstream, stage):
    nodes = {node["id"]: node for node in graph["nodes"]}
    links = {canonical(edge): edge for edge in graph["links"]}
    identifiers = {}
    candidates = {}
    qualified_candidates = {}
    stage_slug = re.sub(r"[^a-z0-9]+", "_", str(stage).casefold()).strip("_") + "_"
    file_slugs = {}
    for node in graph["nodes"]:
        key = (node.get("source_file"), node.get("label"))
        candidates.setdefault(key, []).append(node)
        if node.get("kind") in {"class", "function"}:
            key = (node["source_file"], node["label"].rsplit(".", 1)[-1], node.get("line"))
            qualified_candidates.setdefault(key, []).append(node)
        if node.get("kind") == "file":
            slug = re.sub(r"[^a-z0-9]+", "_", node["id"].casefold()).strip("_")
            file_slugs.setdefault(slug, []).append(node["id"])

    def source_line(value):
        match = re.fullmatch(r"L(\d+)(?:-L?\d+)?", str(value.get("source_location", "")))
        return int(match.group(1)) if match else value.get("line")

    for node in upstream.get("nodes", []):
        source = node.get("source_file", "").replace("\\", "/")
        prefix = stage.as_posix().rstrip("/") + "/"
        if source.startswith(prefix):
            source = source[len(prefix):]
        source = source.removeprefix("./")
        if source not in nodes or nodes[source].get("kind") != "file":
            continue
        old = str(node["id"])
        label = str(node.get("label", node.get("name", old)))[:400]
        label = label.replace(stage.as_posix(), ".").replace(str(stage), ".")
        kind = str(node.get("type", node.get("kind", "symbol")))
        line = source_line(node)
        symbol_name = label.removesuffix("()").lstrip(".")
        matches = candidates.get((source, symbol_name), [])
        matches = [item for item in matches if line is None or item.get("line") == line]
        if not matches and node.get("_callable") and isinstance(line, int):
            matches = qualified_candidates.get((source, symbol_name, line), [])
        if label == PurePosixPath(source).name:
            identifier = source
        elif len(matches) == 1:
            identifier = matches[0]["id"]
        else:
            identifier = "graphify:" + digest(canonical([source, label, kind, line]))
        identifiers[old] = identifier
        nodes.setdefault(identifier, {
            "id": identifier, "label": label, "kind": kind, "source_file": source,
            "file_type": node.get("file_type", Path(source).suffix.lstrip(".")),
            "evidence": "static", "resolution": "resolved", "ownership": ownership(source),
            **({"line": line} if isinstance(line, int) else {}),
            "extractor": "Graphify",
        })
        if identifier != source:
            edge = {"source": source, "target": identifier, "relation": "contains",
                    "source_file": source, "evidence": "static", "resolution": "resolved"}
            links[canonical(edge)] = edge
    for edge in upstream.get("links", upstream.get("edges", [])):
        source = identifiers.get(str(edge.get("_src", edge.get("source"))))
        target = identifiers.get(str(edge.get("_tgt", edge.get("target"))))
        if source is None:
            continue
        resolution = "resolved"
        if target is None:
            label = str(edge.get("_python_import_module", edge.get("_tgt", edge.get("target", "unknown"))))
            label = label.replace(stage.as_posix(), ".").replace(str(stage), ".")
            if re.fullmatch(r"ambiguous_python_import_[a-f0-9]+", label):
                # Upstream salts this opaque ambiguity marker with absolute checkout paths.
                label = f"Ambiguous Python import group at line {source_line(edge) or 'unknown'}"
            if label.startswith(stage_slug):
                label = label[len(stage_slug):]
                matches = file_slugs.get(label, [])
                if len(matches) == 1:
                    target = matches[0]
            if target is None:
                target = "graphify-unresolved:" + digest(canonical([nodes[source]["source_file"], label]))
                nodes.setdefault(target, {
                    "id": target, "label": label[:200], "kind": "reference", "source_file": nodes[source]["source_file"],
                    "evidence": "static", "resolution": "unresolved", "boundary": "external_or_unindexed",
                    "ownership": "external", "extractor": "Graphify",
                })
                resolution = "unresolved"
        confidence = str(edge.get("confidence", "")).casefold()
        result = {"source": source, "target": target, "relation": edge.get("relation", "related"),
                  "source_file": nodes[source]["source_file"],
                  "evidence": "inferred" if "infer" in confidence else "static",
                  "resolution": resolution, "extractor": "Graphify"}
        if isinstance(source_line(edge), int):
            result["line"] = source_line(edge)
        links[canonical(result)] = result
    graph["nodes"] = sorted(nodes.values(), key=lambda item: item["id"])
    graph["links"] = sorted(links.values(), key=canonical)
    graph.setdefault("graph", {})["graphify_import"] = {
        "raw_nodes": len(upstream.get("nodes", [])), "mapped_nodes": len(identifiers),
        "raw_edges": len(upstream.get("links", upstream.get("edges", []))),
        "unmapped_source_nodes": len(upstream.get("nodes", [])) - len(identifiers),
    }
    return len(identifiers)


def source_identity(root):
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    changes = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
                             capture_output=True, text=True, check=True).stdout
    return {"revision": revision, "dirty": bool(changes.strip()),
            "snapshot_kind": "dirty_local" if changes.strip() else "clean_revision"}


def generate(root, output):
    root, output = root.resolve(), output.resolve()
    version = importlib.metadata.version("graphifyy")
    if version != "0.9.72":
        raise RuntimeError("Use the reviewed Graphify 0.9.72 development lock before generating.")
    inputs, excluded = select_inputs(root)
    graph, coverage = Builder(inputs).build()
    with tempfile.TemporaryDirectory(prefix="aifactory-graph-") as temporary:
        temporary = Path(temporary)
        stage, out = temporary / "source", temporary / "result"
        stage.mkdir()
        # Feed only selected code to Graphify, never original notebooks or config values.
        for path, text in inputs.items():
            suffix = Path(path).suffix.casefold()
            if suffix not in {".py", ".sh", ".ps1", ".toml"}:
                continue
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        extract, cluster = graphify_commands(stage, out)
        extraction_log = run_graphify(extract, temporary)
        partial = re.search(r"warning:\s*(\d+) file\(s\) had syntax errors", extraction_log)
        coverage["graphify_partial_syntax_files"] = int(partial.group(1)) if partial else 0
        upstream_file = out / "graphify-out" / "graph.json"
        upstream = json.loads(upstream_file.read_text(encoding="utf-8"))
        coverage["graphify_nodes_merged"] = merge_upstream(graph, upstream, stage)
        if not coverage["graphify_nodes_merged"]:
            raise RuntimeError("Graphify produced no matching source nodes; refusing an adapter-only snapshot.")
        # v0.9.72 clustering can lose parallel edges. Only cluster the disposable upstream copy.
        run_graphify(cluster, temporary)
        # Preserve Graphify's report provenance, but publish adapter coverage too.
        upstream_report = (out / "graphify-out" / "GRAPH_REPORT.md").read_text(encoding="utf-8")
        upstream_report = upstream_report.replace(str(stage), ".").replace(stage.as_posix(), ".")
        view, labels = html_projection(graph)
        view_dir = temporary / "html-view"
        view_dir.mkdir()
        view_graph, view_labels = view_dir / "graph.json", view_dir / "labels.json"
        view_graph.write_text(canonical(view), encoding="utf-8")
        view_labels.write_text(canonical(labels), encoding="utf-8")
        run_graphify(["export", "html", "--graph", str(view_graph), "--labels", str(view_labels)], temporary)
        html = (view_dir / "graph.html").read_text(encoding="utf-8")
    coverage["excluded_counts"] = dict(sorted(Counter(item["reason"] for item in excluded).items()))
    coverage["inferred_edges"] = sum(e["evidence"] == "inferred" for e in graph["links"])
    coverage["unresolved_references"] = sum(e["resolution"] == "unresolved" for e in graph["links"])
    coverage["graphify_import"] = graph["graph"]["graphify_import"]
    coverage["nodes"], coverage["edges"] = len(graph["nodes"]), len(graph["links"])
    report = "# Structural graph coverage\n\n" + "\n".join("- " + item for item in LIMITATIONS)
    report += ("\n\nThe HTML is an aggregate source-boundary overview of the enriched graph, not a lossless directed view. "
               "Graphify 0.9.72 report communities describe its separate disposable native-code graph. "
               "Query graph.json through the shared runtime for authoritative direction and parallel relationships.\n\n")
    report += "\n\n```json\n" + json.dumps(coverage, indent=2) + "\n```\n\n## Upstream Graphify report\n\n" + upstream_report
    vault = root / "documentation" / "architecture"
    notes = {}
    for path in sorted(vault.rglob("*.md")):
        if path.is_symlink() or any(part.startswith(".") for part in path.relative_to(vault).parts):
            raise ValueError("Vault contains nonportable or linked note content")
        notes[path.relative_to(vault).as_posix()] = path.read_bytes().decode("utf-8-sig")
    if not notes:
        raise RuntimeError("Architecture vault is empty; refusing structural-only publication")
    records = [{"path": path, "sha256": input_digest(root / path, content),
                "hash_mode": "notebook_code" if path.endswith(".ipynb") else "raw"}
               for path, content in inputs.items()]
    records.extend({"path": f"documentation/architecture/{path}", "sha256": input_digest(vault / path, content), "hash_mode": "raw"}
                   for path, content in notes.items())
    metadata = {
        "source": source_identity(root), "tools": {"graphifyy": version, "adapter_schema": 1,
                                                  "dependency_lock_sha256": digest(Path(__file__).with_name("requirements.lock.txt").read_bytes())},
        "inputs": sorted(records, key=lambda item: item["path"]), "coverage": coverage,
        "exclusions": excluded,
        "selection": selection_metadata(excluded),
        "settings": {"roots": list(ROOTS), "extensions": sorted(EXTENSIONS), "excluded_dirs": sorted(EXCLUDED_DIRS),
                     "json_allowlist": list(JSON_ALLOWLIST), "max_file_bytes": MAX_FILE_BYTES,
                     "mode": "static_only", "network": "denied_in_graphify_python"},
    }
    sys.path.insert(0, str(root / "usecase_code" / "40-agent-factory" / "40-aifactory-agent"))
    from aifactory_agent.dual_graph import publish_snapshot
    return publish_snapshot(output, graph, notes, metadata, report=report, html=html)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.repository_root, args.output or args.repository_root / "meta" / "graphify"), indent=2))


if __name__ == "__main__":
    main()
