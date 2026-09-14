"""Offline, compiler-backed feature parameter coverage (not ARM simulation).

Compile each pipeline entrypoint once, including its reachable local modules.
Bind deterministic variations to that exact emitted ARM template with Bicep's
build-params command. Pair coverage concerns parameter inputs, NOT resource
conditions, runtime dependencies, or all 2**N deployments.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from base import config


class MatrixError(ValueError):
    """A failed or unsupported offline contract; never an implicit skip."""


@dataclass(frozen=True)
class Feature:
    name: str
    kind: str
    default: bool | str
    default_source: str

    def value(self, enabled: bool) -> bool | str:
        return enabled if self.kind == "bool" else str(enabled).lower()


@dataclass(frozen=True)
class Case:
    name: str
    values: dict[str, bool | str]


FEATURE_PREFIX = re.compile(r"^(?:enable|disable|add|allow)(?:[A-Z_]|$)")
REQUIRED_INPUT_FIXTURES = {
    "azureOpenAIBackends": [{
        "name": "offline-backend", "endpoint": "https://offline.invalid",
        "resourceId": "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/offline/providers/Microsoft.CognitiveServices/accounts/offline",
        "weight": 1, "priority": 1,
    }],
}
LIMITS = [
    "Scope: literal --template-file entrypoints in the committed GHA/ADO pipeline "
    "templates and every reachable local Bicep/ARM module; not orphaned/retired templates. "
    "Registry module references are reported and require a pre-populated Bicep cache; "
    "--no-restore fails when a dependency is absent.",
    "Flags: all entrypoint bool parameters and true/false-string parameters. "
    "The flags count is template/parameter occurrences, not distinct names. "
    "Nested object properties and module-only inputs are not varied.",
    "All-off/all-on mean false/true INPUTS, including disable flags, not all Azure "
    "features disabled/enabled. Cases are type-valid bindings, not certified deployments.",
    "Coverage is baseline, individual flips, and all four input states of every "
    "pair within each entrypoint; not every 2**N assignment or cross-entrypoint pairs.",
    "Baseline uses real Bicep defaults; required flags use committed ADO defaults, "
    "with a separate GHA-required-defaults case. Expression defaults support only "
    "parameters(), not(), and boolean literals; other expressions fail explicitly.",
    "Every case explicitly binds all flags; derived flag defaults are resolved only "
    "for the baseline and are intentionally overridden in variations.",
    "Bicep compiles source once per entrypoint; build-params validates every case "
    "against its exact emitted ARM JSON. No Azure login, restore, validation, what-if, "
    "deployment, or evaluation of ARM resource conditions/dependsOn occurs.",
    "Required non-flag inputs use synthetic type/constraint-valid placeholders. "
    "Azure names, credentials, quotas, existence, RBAC and service dependencies "
    "(for example AKS/ML or private-network prerequisites) are not verified.",
]


def discover_entrypoints(repo: Path) -> list[Path]:
    """Find literal deployment roots from both committed pipeline template trees."""
    base = repo / "environment_setup" / "aifactory" / "bicep"
    source = base / "copy_to_local_settings"
    roots: set[Path] = set()
    for directory in (source / "github-actions", source / "azure-devops"):
        if not directory.is_dir():
            raise MatrixError(f"Missing pipeline template directory: {directory}")
        for path in sorted(directory.rglob("*")):
            if path.suffix not in {".yaml", ".yml"}:
                continue
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if line.lstrip().startswith("#") or "--template-file" not in line:
                    continue
                match = re.search(r"""--template-file(?:\s+|=)(["'])(.+?)\1""", line)
                if not match:
                    raise MatrixError(f"Unsupported template-file reference in {path}: {line.strip()}")
                ref = match[2].replace("\\", "/")
                if "environment_setup/" in ref:
                    candidate = repo / ref[ref.index("environment_setup/"):]
                elif ref.startswith(("esml-common/", "esml-genai-1/")):
                    candidate = base / ref
                else:
                    raise MatrixError(f"Unresolved template-file reference in {path}: {ref}")
                candidate = candidate.resolve()
                if not candidate.is_relative_to(repo.resolve()) or not candidate.is_file():
                    raise MatrixError(f"Missing or out-of-repository entrypoint: {candidate}")
                if candidate.suffix != ".bicep":
                    raise MatrixError(f"Unsupported entrypoint type: {candidate}")
                roots.add(candidate)
    if not roots:
        raise MatrixError("No production Bicep entrypoints discovered")
    return sorted(roots)


def _without_comments(source: str) -> str:
    tokens = r"'''[\s\S]*?'''|'(?:\\.|[^'\\])*'|//[^\n]*|/\*[\s\S]*?\*/"
    return re.sub(
        tokens,
        lambda m: "\n" * m[0].count("\n")
        if m[0].startswith(("//", "/*", "'''")) else m[0],
        source,
    )


def reachable_templates(
    roots: list[Path], repo: Path, registry_modules: set[str] | None = None,
) -> list[Path]:
    """Count local sources and explicitly inventory cached registry dependencies."""
    visited: set[Path] = set()
    pending = list(roots)
    while pending:
        path = pending.pop().resolve()
        if path in visited:
            continue
        if not path.is_relative_to(repo.resolve()) or not path.is_file():
            raise MatrixError(f"Missing or out-of-repository module: {path}")
        visited.add(path)
        if path.suffix == ".json":
            continue
        source = _without_comments(path.read_text(encoding="utf-8-sig"))
        declarations = re.findall(r"(?m)^\s*module\s+\w+\s+([^\n]+)", source)
        for declaration in declarations:
            match = re.match(r"'([^']+)'", declaration)
            if match and match[1].startswith(("br:", "br/")) and "${" not in match[1]:
                if registry_modules is None:
                    raise MatrixError(f"Registry module must be explicitly inventoried: {match[1]}")
                registry_modules.add(match[1])
                continue
            if not match or ":" in match[1] or "${" in match[1]:
                raise MatrixError(f"Unsupported non-local module in {path}: {declaration}")
            pending.append(path.parent / match[1])
        imports = re.findall(
            r"(?ms)^\s*import\b.*?\bfrom\s+'([^']+)'", source)
        for reference in imports:
            if reference.startswith(("br:", "br/")) and "${" not in reference:
                if registry_modules is None:
                    raise MatrixError(
                        f"Registry import must be explicitly inventoried: {reference}")
                registry_modules.add(reference)
                continue
            if ":" in reference or "${" in reference:
                raise MatrixError(f"Unsupported non-local import in {path}: {reference}")
            pending.append(path.parent / reference)
    return sorted(visited)


def _is_boolean_string(value: Any) -> bool:
    return type(value) is str and value in ("true", "false")


def inventory_features(
    parameters: dict[str, Any], required_defaults: dict[str, bool | str] | None = None,
) -> list[Feature]:
    """Discover flags from compiler output, failing on unknown flag shapes/defaults."""
    required_defaults = required_defaults or {}
    candidates = {}
    for name, spec in parameters.items():
        kind = spec.get("type")
        allowed = spec.get("allowedValues", [])
        boolean_string = kind == "string" and (
            _is_boolean_string(spec.get("defaultValue"))
            or (bool(allowed) and all(_is_boolean_string(v) for v in allowed))
        )
        if kind == "bool" or boolean_string:
            candidates[name] = spec
        elif FEATURE_PREFIX.match(name):
            raise MatrixError(f"Unsupported feature parameter {name}: {spec}")

    resolved: dict[str, bool | str] = {}

    def resolve(name: str, stack: tuple[str, ...] = ()) -> bool | str:
        if name in resolved:
            return resolved[name]
        if name in stack:
            raise MatrixError(f"Cyclic feature default: {' -> '.join((*stack, name))}")
        if name not in candidates:
            raise MatrixError(f"Feature default references unsupported parameter: {name}")
        spec = candidates[name]
        if "defaultValue" in spec:
            value = spec["defaultValue"]
        elif name in required_defaults:
            value = required_defaults[name]
        else:
            raise MatrixError(f"Required feature {name} has no declared/configured baseline")

        def expression(text: str) -> bool | str:
            reference = re.fullmatch(r"parameters\('(\w+)'\)", text)
            if reference:
                return resolve(reference[1], (*stack, name))
            negation = re.fullmatch(r"not\((.+)\)", text)
            if negation:
                operand = expression(negation[1])
                if type(operand) is not bool:
                    raise MatrixError(f"not() requires a boolean default in {name}")
                return not operand
            if text in ("true()", "false()"):
                return text == "true()"
            raise MatrixError(f"Unsupported feature default expression for {name}: [{text}]")

        if type(value) is str and value.startswith("[") and value.endswith("]"):
            value = expression(value[1:-1])
        valid = type(value) is bool if spec["type"] == "bool" else _is_boolean_string(value)
        if not valid:
            raise MatrixError(f"Wrong baseline type for feature {name}: {value!r}")
        allowed = spec.get("allowedValues")
        both = [False, True] if spec["type"] == "bool" else ["false", "true"]
        if allowed is not None and (
            len(allowed) != 2
            or any(type(a) is not type(both[0]) for a in allowed)
            or set(allowed) != set(both)
        ):
            raise MatrixError(f"Feature {name} does not permit both states: {allowed!r}")
        resolved[name] = value
        return value

    return [
        Feature(name, spec["type"], resolve(name),
                "bicep" if "defaultValue" in spec else "ado-required-default")
        for name, spec in sorted(candidates.items())
    ]


def generate_cases(features: list[Feature]) -> list[Case]:
    """Binary index rows/complements cover every mixed pair in O(log N) rows."""
    baseline = {f.name: f.default for f in features}
    cases = [Case("baseline", baseline)]
    if not features:
        return cases
    cases.extend(Case(label, {f.name: f.value(state) for f in features})
                 for label, state in (("all_off", False), ("all_on", True)))
    for feature in features:
        values = dict(baseline)
        values[feature.name] = feature.value(feature.default in (False, "false"))
        cases.append(Case(f"toggle_{feature.name}", values))
    for bit in range(math.ceil(math.log2(len(features)))):
        for complement in (False, True):
            cases.append(Case(
                f"pair_bit_{bit}_{int(complement)}",
                {f.name: f.value(bool((index >> bit) & 1) ^ complement)
                 for index, f in enumerate(features)},
            ))
    return cases


def verify_cases(features: list[Feature], cases: list[Case]) -> int:
    """Independently check completeness, exact types, individual and pair coverage."""
    expected = {f.name for f in features}
    by_name = {case.name: case for case in cases}
    if len(by_name) != len(cases):
        raise MatrixError("Duplicate matrix case name")
    for case in cases:
        if set(case.values) != expected:
            raise MatrixError(f"{case.name}: missing/extra flags: "
                              f"{sorted(expected - set(case.values))}/"
                              f"{sorted(set(case.values) - expected)}")
        for feature in features:
            value = case.values[feature.name]
            valid = type(value) is bool if feature.kind == "bool" else _is_boolean_string(value)
            if not valid:
                raise MatrixError(f"{case.name}: wrong type for {feature.name}: {value!r}")
    baseline = {f.name: f.default for f in features}
    if "baseline" not in by_name or by_name["baseline"].values != baseline:
        raise MatrixError("Missing/incorrect actual-default baseline")
    if not features:
        return 0
    for label, state in (("all_off", False), ("all_on", True)):
        if label not in by_name or by_name[label].values != {f.name: f.value(state) for f in features}:
            raise MatrixError(f"Missing/incorrect {label} case")
    for feature in features:
        values = dict(baseline)
        values[feature.name] = feature.value(feature.default in (False, "false"))
        case = by_name.get(f"toggle_{feature.name}")
        if case is None or case.values != values:
            raise MatrixError(f"Missing/incorrect individual toggle for {feature.name}")
    count = 0
    for left, right in itertools.combinations(features, 2):
        covered = {(case.values[left.name], case.values[right.name]) for case in cases}
        required = set(itertools.product((left.value(False), left.value(True)),
                                         (right.value(False), right.value(True))))
        if covered != required:
            raise MatrixError(f"Missing pair states for {left.name}/{right.name}: {required - covered}")
        count += len(required)
    return count


def required_flag_defaults() -> tuple[dict[str, bool], dict[str, bool]]:
    """Only required flags need explicit mappings; all defaulted flags are discovered."""
    mappings = {
        "addBastionHost": ("addBastionHost", "ADD_BASTION_HOST"),
        "hybridBenefit": ("admin_hybridBenefit", "ADMIN_HYBRID_BENEFIT"),
    }
    ado, github = config.parse_yaml_vars(), config.parse_env_template()
    results: tuple[dict[str, bool], dict[str, bool]] = ({}, {})
    for name, keys in mappings.items():
        for output, source, key in zip(results, (ado, github), keys):
            value = source.get(key)
            if not _is_boolean_string(value):
                raise MatrixError(f"Invalid required flag configuration: {key}={value!r}")
            output[name] = value == "true"
    return results


def required_bindings(parameters: dict[str, Any], flags: set[str]) -> dict[str, Any]:
    """Synthetic required inputs for compile-time binding only; never deploy these."""
    values = {}
    for name, spec in parameters.items():
        if name in flags or "defaultValue" in spec:
            continue
        kind = spec.get("type")
        if name in REQUIRED_INPUT_FIXTURES:
            value = REQUIRED_INPUT_FIXTURES[name]
            if spec.get("type") != "array" or not (
                spec.get("minLength", 0) <= len(value) <= spec.get("maxLength", len(value))
            ):
                raise MatrixError(f"Required input fixture no longer matches schema: {name}")
        elif spec.get("allowedValues"):
            value = spec["allowedValues"][0]
        elif kind in ("string", "securestring"):
            length = max(12, spec.get("minLength", 0))
            length = min(length, spec.get("maxLength", length))
            value = ("offline-test" * (length + 1))[:length]
        elif kind == "int":
            value = max(0, spec.get("minValue", 0))
            value = min(value, spec.get("maxValue", value))
        elif kind == "array":
            if spec.get("minLength", 0) > 0 or "items" in spec:
                raise MatrixError(f"Required structured array needs an explicit fixture: {name}")
            value = []
        elif kind in ("object", "secureobject"):
            if "properties" in spec or "additionalProperties" in spec:
                raise MatrixError(f"Required structured object needs an explicit fixture: {name}")
            value = {}
        else:
            raise MatrixError(f"Unsupported required parameter {name}: {spec}")
        values[name] = value
    return values


def bicep_literal(value: Any) -> str:
    if type(value) is bool:
        return str(value).lower()
    if type(value) is int:
        return str(value)
    if type(value) is str:
        escaped = (value.replace("\\", "\\\\").replace("'", "\\'")
                   .replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
                   .replace("${", "\\${"))
        return f"'{escaped}'"
    if type(value) in (list, dict):
        return f"json({bicep_literal(json.dumps(value, separators=(',', ':')))})"
    raise MatrixError(f"Unsupported Bicep fixture literal: {value!r}")


@contextmanager
def work_directory(repo: Path) -> Iterator[Path]:
    """Keep generated files in an isolated repository child and always remove it."""
    path = repo / f".offline-bicep-work-{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


class Compiler:
    def __init__(self, executable: str, repo: Path):
        found = shutil.which(executable)
        if not found:
            raise MatrixError(f"Bicep CLI is required but not found: {executable}")
        self.executable = found
        self.repo = repo
        self.invocations = 0

    def run(self, *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
        self.invocations += 1
        env = dict(os.environ)
        env.pop("BICEP_PARAMETERS_OVERRIDES", None)
        try:
            return subprocess.run(
                [self.executable, *args], cwd=self.repo, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MatrixError(f"Bicep invocation failed: {args}: {exc}") from exc

    def checked(self, *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
        result = self.run(*args, timeout=timeout)
        if result.returncode:
            raise MatrixError(f"Bicep {' '.join(args)} failed ({result.returncode}):\n{result.stderr}")
        return result


def run_matrix(repo: Path, executable: str, jobs: int = 2) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "failed", "mode": "offline-validation", "limits": LIMITS, "templates": [], "errors": [],
        "counts": {"entrypoints": 0, "compiled_entrypoints": 0, "reachable_source_templates": 0,
                   "flags": 0, "cases": 0, "bound_cases": 0, "pair_states": 0,
                   "compiler_invocations": 0},
    }
    compiler = None
    try:
        compiler = Compiler(executable, repo)
        report["bicep_version"] = compiler.checked("--version").stdout.strip()
        roots = discover_entrypoints(repo)
        registry_modules: set[str] = set()
        reachable = reachable_templates(roots, repo, registry_modules)
        report["counts"]["entrypoints"] = len(roots)
        report["counts"]["reachable_source_templates"] = len(reachable)
        report["reachable_source_templates"] = [p.relative_to(repo).as_posix() for p in reachable]
        report["registry_module_dependencies"] = sorted(registry_modules)
        ado_defaults, github_defaults = required_flag_defaults()
        with work_directory(repo) as work:
            def compile_one(path: Path) -> tuple[Path, Any]:
                try:
                    result = compiler.checked("build", str(path), "--stdout", "--no-restore")
                    return path, (json.loads(result.stdout), result.stderr)
                except (MatrixError, json.JSONDecodeError) as exc:
                    return path, exc

            bindings: dict[str, dict[str, Any]] = {}
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                for index, (path, result) in enumerate(pool.map(compile_one, roots)):
                    entry: dict[str, Any] = {"file": path.relative_to(repo).as_posix(), "status": "failed"}
                    report["templates"].append(entry)
                    if isinstance(result, Exception):
                        report["errors"].append(str(result))
                        continue
                    arm, diagnostics = result
                    report["counts"]["compiled_entrypoints"] += 1
                    entry["compiler_warnings"] = sum("Warning " in line for line in diagnostics.splitlines())
                    try:
                        parameters = arm.get("parameters", {})
                        features = inventory_features(parameters, ado_defaults)
                        cases = generate_cases(features)
                        if any(f.default_source != "bicep" for f in features):
                            values = {f.name: (github_defaults[f.name] if f.default_source != "bicep"
                                              else f.default) for f in features}
                            cases.append(Case("baseline_github_required", values))
                        pairs = verify_cases(features, cases)
                        extra = required_bindings(parameters, {f.name for f in features})
                        stem = f"template_{index:03}"
                        (work / f"{stem}.json").write_text(json.dumps(arm), encoding="utf-8")
                        entry["flags"] = [
                            {"name": f.name, "type": f.kind, "baseline": f.default,
                             "default_source": f.default_source,
                             "declared_default": parameters[f.name].get("defaultValue")}
                            for f in features
                        ]
                        entry["cases"] = [{"name": c.name, "flags": c.values} for c in cases]
                        entry["synthetic_required_parameters"] = sorted(extra)
                        entry["pair_states"] = pairs
                        for case_index, case in enumerate(cases):
                            case_stem = f"{stem}_case_{case_index:03}"
                            bound = {**extra, **case.values}
                            text = f"using './{stem}.json'\n" + "".join(
                                f"param {name} = {bicep_literal(value)}\n" for name, value in sorted(bound.items())
                            )
                            (work / f"{case_stem}.bicepparam").write_text(text, encoding="utf-8")
                            bindings[case_stem] = bound
                        entry["status"] = "compiled"
                        report["counts"]["flags"] += len(features)
                        report["counts"]["cases"] += len(cases)
                        report["counts"]["pair_states"] += pairs
                    except MatrixError as exc:
                        report["errors"].append(f"{entry['file']}: {exc}")
            if bindings:
                output = work / "bound"
                output.mkdir()
                compiler.checked("build-params", "--pattern", str(work / "*.bicepparam"),
                                 "--outdir", str(output), "--no-restore", timeout=900)
                for stem, expected in bindings.items():
                    path = output / f"{stem}.json"
                    if not path.is_file():
                        raise MatrixError(f"Bicep build-params did not produce {path.name}")
                    actual = {k: v["value"] for k, v in json.loads(path.read_text(encoding="utf-8-sig"))["parameters"].items()}
                    if actual != expected or any(type(actual[k]) is not type(expected[k]) for k in actual):
                        raise MatrixError(f"Bicep parameter round-trip mismatch: {stem}")
                    report["counts"]["bound_cases"] += 1
                for entry in report["templates"]:
                    if entry["status"] == "compiled":
                        entry["status"] = "passed"
            if not report["errors"]:
                report["status"] = "passed"
    except (MatrixError, OSError, KeyError, json.JSONDecodeError) as exc:
        report["errors"].append(str(exc))
    finally:
        if compiler is not None:
            report["counts"]["compiler_invocations"] = compiler.invocations
    return report


def public_registry_reference(reference: str) -> str:
    """Cache preparation is deliberately restricted to versioned public AVM modules."""
    match = re.fullmatch(
        r"(?:br/public:|br:mcr\.microsoft\.com/bicep/)"
        r"(avm/[a-z0-9][a-z0-9/-]*:[0-9]+\.[0-9]+\.[0-9]+)",
        reference,
    )
    if not match:
        raise MatrixError(f"Cache preparation supports only pinned public AVM modules: {reference}")
    return f"br:mcr.microsoft.com/bicep/{match[1]}"


def prepare_cache(repo: Path, executable: str) -> dict[str, Any]:
    """Explicit network-enabled dependency preparation; never run by validation."""
    report: dict[str, Any] = {
        "status": "failed", "mode": "public-cache-preparation", "errors": [],
        "limits": [
            "May access mcr.microsoft.com to restore declared, version-pinned public "
            "AVM modules into the Bicep cache. No Azure login or deployment.",
            "This is dependency preparation, NOT offline validation. Run the normal "
            "matrix command separately; it always uses --no-restore.",
        ],
        "counts": {"entrypoints": 0, "requested_registry_modules": 0, "compiler_invocations": 0},
    }
    compiler = None
    try:
        compiler = Compiler(executable, repo)
        report["bicep_version"] = compiler.checked("--version").stdout.strip()
        roots = discover_entrypoints(repo)
        references: set[str] = set()
        reachable_templates(roots, repo, references)
        public = sorted({public_registry_reference(reference) for reference in references})
        report["counts"]["entrypoints"] = len(roots)
        report["counts"]["requested_registry_modules"] = len(public)
        report["declared_registry_modules"] = sorted(references)
        report["public_restore_references"] = public
        if public:
            with work_directory(repo) as work:
                source = work / "public-cache.bicep"
                source.write_text("\n".join(
                    f"module dependency{index} '{reference}' = {{\n  name: 'cache{index}'\n}}\n"
                    for index, reference in enumerate(public)
                ), encoding="utf-8")
                result = compiler.checked("restore", str(source), timeout=900)
                report["restore_output"] = {"stdout": result.stdout, "stderr": result.stderr}
        report["status"] = "passed"
    except (MatrixError, OSError) as exc:
        report["errors"].append(str(exc))
    finally:
        if compiler is not None:
            report["counts"]["compiler_invocations"] = compiler.invocations
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Required offline Bicep compiler and feature-parameter gate.")
    parser.add_argument("--bicep", default="bicep", help="Standalone Bicep executable (required, never skipped)")
    parser.add_argument("--report", required=True, type=Path, help="JSON report output path")
    parser.add_argument("--jobs", default=2, type=int, choices=range(1, 9), help="Parallel entrypoint compiles (1-8)")
    parser.add_argument("--prepare-cache", action="store_true",
                        help="Explicit NETWORK-ENABLED public AVM dependency restore, then exit (no validation)")
    args = parser.parse_args(argv)
    report = (prepare_cache(config.REPO_ROOT, args.bicep) if args.prepare_cache
              else run_matrix(config.REPO_ROOT, args.bicep, args.jobs))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "mode": report["mode"],
                      "counts": report["counts"], "report": str(args.report)}))
    for error in report["errors"]:
        print(error, file=sys.stderr)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
