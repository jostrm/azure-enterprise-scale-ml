"""Credential-free infrastructure checks shared by GitHub Actions and Azure Pipelines."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

from base.config import REPO_ROOT


SUITE = Path(__file__).resolve().parent


class UniqueKeyLoader(yaml.SafeLoader):
    """Keep GitHub's 'on' key a string and reject silently overwritten mappings."""


UniqueKeyLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in values if tag != "tag:yaml.org,2002:bool"]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
UniqueKeyLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false|True|False|TRUE|FALSE)$"), list("tTfF")
)


def unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while reading a mapping", node.start_mark,
                f"duplicate key {key!r}", key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def offline_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["LIVE_AZURE"] = "0"
    environment["PYTHONUTF8"] = "1"
    for name in ("BASH_ENV", "ENV", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        environment.pop(name, None)
    tools = [str(Path(sys.executable).parent)]
    if os.name == "nt":
        tools.insert(0, str(Path(find_bash()).parent))
    environment["PATH"] = os.pathsep.join([*tools, environment.get("PATH", "")])
    return environment


def offline_test_paths(suite: Path = SUITE) -> list[str]:
    # Explicit paths include the older root-level regression tests, never integration/.
    return [str(suite / "unit"), *(str(path) for path in sorted(suite.glob("test_*.py")))]


def find_bash() -> str:
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    executable = shutil.which("bash")
    if not executable:
        raise RuntimeError("Bash is required. Install Git Bash on Windows or Bash on Linux.")
    return executable


def syntax_files(root: Path) -> list[Path]:
    roots = [
        root / ".github" / "workflows",
        root / "bootstrap",
        root / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings",
        root / "environment_setup" / "aifactory" / "bicep" / "scripts",
        root / "environment_setup" / "unit-tests" / "test-bicep",
    ]
    return sorted({
        path for directory in roots for path in directory.rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".yml", ".sh", ".py"}
        and not any(part in {".venv", "__pycache__", "test-results", ".pytest_cache"} for part in path.parts)
    } | ({root / "00-start.sh"} if (root / "00-start.sh").is_file() else set()))


def check_syntax(root: Path, bash: str) -> dict:
    counts = {"yaml": 0, "bash": 0, "python": 0}
    failures = []
    for path in syntax_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            if path.suffix == ".sh" and b"\r" in path.read_bytes():
                failures.append({"path": relative, "error": "Bash source must use LF line endings; CRLF breaks Linux execution."})
                continue
            source = path.read_text(encoding="utf-8-sig")
            if path.suffix in {".yaml", ".yml"}:
                list(yaml.load_all(source, Loader=UniqueKeyLoader))
                counts["yaml"] += 1
            elif path.suffix == ".py":
                ast.parse(source, filename=relative)
                counts["python"] += 1
            else:
                result = subprocess.run(
                    [bash, "--noprofile", "--norc", "-n"], input=source, text=True,
                    encoding="utf-8", capture_output=True, timeout=30, env=offline_environment(), check=False,
                )
                if result.returncode:
                    failures.append({"path": relative, "error": result.stderr.strip()})
                counts["bash"] += 1
        except (UnicodeError, SyntaxError, yaml.YAMLError, OSError, subprocess.TimeoutExpired) as error:
            failures.append({"path": relative, "error": str(error)})
    return {"checked": counts, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("all", "unit", "syntax", "bicep"), default="all")
    parser.add_argument("--bicep", default="bicep", help="Bicep CLI executable; required for the compiler phase")
    parser.add_argument("--require-ci-tools", action="store_true",
                        help="Fail if Git or PowerShell Core is missing instead of leaving those unit tests skipped")
    parser.add_argument("--results-dir", type=Path, default=SUITE / "test-results")
    args = parser.parse_args(argv)
    results = args.results_dir.resolve()
    results.mkdir(parents=True, exist_ok=True)
    failures = []
    phases = ("unit", "syntax", "bicep") if args.phase == "all" else (args.phase,)
    for phase in phases:
        started = time.monotonic()
        print(f"=== Offline IaC: {phase} ===", flush=True)
        try:
            if phase == "syntax":
                report = check_syntax(REPO_ROOT, find_bash())
                (results / "syntax.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(report, indent=2), flush=True)
                code = int(bool(report["failures"]))
            elif phase == "unit":
                find_bash()
                if args.require_ci_tools:
                    tool_path = offline_environment()["PATH"]
                    missing = [tool for tool in ("git", "pwsh") if not shutil.which(tool, path=tool_path)]
                    if missing:
                        raise RuntimeError(f"Required CI tools are missing: {', '.join(missing)}")
                with tempfile.TemporaryDirectory(prefix="aifactory-ci-") as temporary:
                    environment = offline_environment()
                    environment["TMPDIR"] = Path(temporary).as_posix()
                    code = subprocess.run(
                        [sys.executable, "-m", "pytest", *offline_test_paths(), "-q", "--tb=short",
                         f"--junitxml={results / 'unit-tests.xml'}"],
                        cwd=SUITE, env=environment, timeout=1200, check=False,
                    ).returncode
                from domain.pipeline_contracts import CONFIG_ONLY_EXCEPTIONS, DEFAULT_EXCEPTIONS, FEATURES
                coverage = {
                    "public_enable_flags": len(FEATURES),
                    "mapped_flag_contracts": len(FEATURES) - len(CONFIG_ONLY_EXCEPTIONS),
                    "configuration_only_or_unwired": CONFIG_ONLY_EXCEPTIONS,
                    "intentional_default_differences": DEFAULT_EXCEPTIONS,
                    "limits": "Offline configuration, mapping and dependency contracts; not Azure deployment proof.",
                }
                (results / "feature-contract-coverage.json").write_text(
                    json.dumps(coverage, indent=2) + "\n", encoding="utf-8"
                )
            else:
                code = subprocess.run(
                    [sys.executable, str(SUITE / "run_bicep_matrix.py"), "--bicep", args.bicep,
                     "--report", str(results / "bicep-matrix.json")],
                    cwd=SUITE, env=offline_environment(), timeout=1200, check=False,
                ).returncode
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            print(f"{phase}: {error}", file=sys.stderr, flush=True)
            code = 1
        if code:
            failures.append(phase)
        print(f"{phase}: {'FAILED' if code else 'passed'} ({time.monotonic() - started:.1f}s)", flush=True)
    summary = {"phases": list(phases), "failed": failures, "azure_deployment_performed": False}
    (results / f"{args.phase}-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
