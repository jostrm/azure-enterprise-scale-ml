#!/usr/bin/env python3
"""Static metrics for GitHub Actions workflows and Azure DevOps pipelines in a purple checkout.

Counts, per entry file: stages, jobs, steps, `az` calls, fixed waits (count and literal seconds),
logins/account switches/extension installs, deployments, Bicep template files and the scripts reached.
Template includes (ADO `template:`) and local reusable workflows (GHA job-level `uses: ./...`) are followed.
Scripts named by a step are followed transitively and reported in separate columns.

Usage: wf_metrics.py --root <repo root> --out <json> [entry files relative to root ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


class Pairs(list):
    """A YAML mapping kept as ordered (key, value) pairs so duplicate `${{ if }}` keys survive."""

    def get(self, key, default=None):
        for k, v in self:
            if k == key:
                return v
        return default

    def keys(self):
        return [k for k, _ in self]


class Loader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node):
    return Pairs((loader.construct_object(k, deep=True), loader.construct_object(v, deep=True)) for k, v in node.value)


Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)

STEP_KEYS = {"task", "script", "bash", "pwsh", "powershell", "checkout", "download", "publish", "run", "uses"}
SCRIPT_SUFFIXES = (".sh", ".ps1", ".py", ".psm1")
AZ_CALL = re.compile(r"(?<![\w./\\-])az\s+(?!-)([a-z][a-z-]+)(?:\s+([a-z][a-z-]+))?(?:\s+([a-z][a-z-]+))?")
SLEEP_PATTERNS = [
    (re.compile(r"(?<![\w.-])sleep\s+(\d+(?:\.\d+)?)([smh]?)(?![\w.])"), "sh"),
    (re.compile(r"Start-Sleep\s+(?:-Seconds\s+|-s\s+)?(\d+(?:\.\d+)?)(?![\w.])", re.I), "ps"),
    (re.compile(r"Start-Sleep\s+-Milliseconds\s+(\d+)", re.I), "psms"),
    (re.compile(r"time\.sleep\(\s*(\d+(?:\.\d+)?)\s*\)"), "py"),
]
VARIABLE_SLEEP = re.compile(
    r"(?<![\w.-])sleep\s+[\"']?\$|Start-Sleep\s+(?:-Seconds\s+|-Milliseconds\s+|-s\s+)?[\$\(]|time\.sleep\(\s*[A-Za-z_(]", re.I)
PATH_TOKEN = re.compile(r"[A-Za-z0-9_$(){}.\-/\\]+\.(?:sh|ps1|py|psm1|bicep|bicepparam|json|yaml|yml)(?![A-Za-z0-9_])")
TEMPLATE_FILE = re.compile(r"(?:--template-file|-TemplateFile|csmFile:)\s*[\"']?([^\s\"'`]+)")
LOGIN = re.compile(r"(?<![\w./\\-])az\s+login(?![\w-])")
ACCOUNT_SET = re.compile(r"(?<![\w./\\-])az\s+account\s+set(?![\w-])")
EXTENSION = re.compile(r"(?<![\w./\\-])az\s+extension\s+(?:add|update)(?![\w-])")
BICEP_INSTALL = re.compile(r"(?<![\w./\\-])az\s+bicep\s+(?:install|upgrade)(?![\w-])")
DEPLOYMENT = re.compile(r"(?<![\w./\\-])az\s+(?:deployment\s+(?:group|sub|mg|tenant)\s+(?:create|what-if|validate)|stack\s+\w+\s+create)")


def strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("#", "::", "REM ")))


def text_metrics(text: str) -> dict:
    body = strip_comments(text)
    sleeps, seconds = 0, 0.0
    for pattern, kind in SLEEP_PATTERNS:
        for match in pattern.finditer(body):
            value = float(match.group(1))
            if kind == "sh":
                value *= {"": 1, "s": 1, "m": 60, "h": 3600}[match.group(2)]
            elif kind == "psms":
                value /= 1000
            sleeps += 1
            seconds += value
    return {
        "az_calls": len(AZ_CALL.findall(body)),
        "sleeps": sleeps,
        "sleep_seconds": round(seconds, 1),
        "variable_sleeps": len(VARIABLE_SLEEP.findall(body)),
        "az_login": len(LOGIN.findall(body)),
        "az_account_set": len(ACCOUNT_SET.findall(body)),
        "az_extension": len(EXTENSION.findall(body)),
        "az_bicep_install": len(BICEP_INSTALL.findall(body)),
        "deployments": len(DEPLOYMENT.findall(body)),
    }


def add(total: dict, part: dict) -> None:
    for key, value in part.items():
        total[key] = round(total.get(key, 0) + value, 1)


class Analyzer:
    def __init__(self, root: Path):
        self.root = root
        self.files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
        self.by_name: dict[str, list[str]] = {}
        for name in self.files:
            self.by_name.setdefault(name.rsplit("/", 1)[-1], []).append(name)

    def resolve(self, token: str, origin: str) -> str | None:
        token = token.replace("\\", "/").strip("\"'`,;()")
        if "azure-enterprise-scale-ml/" in token:
            token = token.split("azure-enterprise-scale-ml/", 1)[1]
        token = re.sub(r"^(?:\$\([^)]*\)|\$\{\{[^}]*\}\}|\$\{[^}]*\}|\$[A-Za-z_]+|\.)/+", "", token)
        token = token.lstrip("./")
        if not token or token.startswith("$"):
            return None
        if token in self.files:
            return token
        origin_dir = origin.rsplit("/", 1)[0] if "/" in origin else ""
        parts = (origin_dir + "/" + token).split("/")
        stack: list[str] = []
        for part in parts:
            if part == "..":
                if stack:
                    stack.pop()
            elif part not in ("", "."):
                stack.append(part)
        candidate = "/".join(stack)
        if candidate in self.files:
            return candidate
        # A unique suffix match, e.g. "scripts/preflight.sh" or "esml-genai-1/01-foundation.bicep".
        matches = [name for name in self.by_name.get(token.rsplit("/", 1)[-1], []) if name.endswith("/" + token) or name == token]
        return matches[0] if len(matches) == 1 else None

    def references(self, text: str, origin: str) -> set[str]:
        found = set()
        for match in PATH_TOKEN.finditer(strip_comments(text)):
            resolved = self.resolve(match.group(0), origin)
            if resolved and resolved != origin:
                found.add(resolved)
        return found

    def script_closure(self, seeds: set[str]) -> set[str]:
        seen: set[str] = set()
        queue = [s for s in seeds if s.endswith(SCRIPT_SUFFIXES)]
        while queue:
            current = queue.pop()
            if current in seen:
                continue
            seen.add(current)
            try:
                text = (self.root / current).read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            for ref in self.references(text, current):
                if ref.endswith(SCRIPT_SUFFIXES) and ref not in seen:
                    queue.append(ref)
        return seen

    def analyze(self, entry: str) -> dict:
        result = {"entry": entry, "stages": 0, "jobs": 0, "steps": 0, "includes": [], "inline": {}, "templates": set(),
                  "direct_refs": set(), "azure_login_actions": 0, "checkouts": 0, "checkout_settings": []}
        self._walk_file(entry, result, depth=0)
        scripts = self.script_closure(result["direct_refs"])
        script_metrics: dict = {}
        per_script = {}
        for script in sorted(scripts):
            text = (self.root / script).read_text(encoding="utf-8-sig", errors="replace")
            metrics = text_metrics(text)
            per_script[script] = metrics
            add(script_metrics, metrics)
            for match in TEMPLATE_FILE.finditer(strip_comments(text)):
                resolved = self.resolve(match.group(1), script)
                result["templates"].add(resolved or match.group(1))
            for ref in self.references(text, script):
                if ref.endswith(".bicep"):
                    result["templates"].add(ref)
        result["scripts"] = sorted(scripts)
        result["script_metrics"] = script_metrics
        result["per_script"] = per_script
        result["templates"] = sorted(result["templates"])
        result["direct_refs"] = sorted(result["direct_refs"])
        return result

    def _walk_file(self, name: str, result: dict, depth: int) -> None:
        if depth > 12:
            return
        try:
            text = (self.root / name).read_text(encoding="utf-8-sig")
        except OSError:
            return
        result["includes"].append(name)
        document = yaml.load(text, Loader=Loader)
        self._walk(document, name, result, depth, context=None)

    def _walk(self, node, origin: str, result: dict, depth: int, context: str | None) -> None:
        if isinstance(node, Pairs):
            keys = set(k for k in node.keys() if isinstance(k, str))
            template = node.get("template")
            if isinstance(template, str) and not ({"stages", "jobs", "steps"} & keys):
                target = self.resolve(template.split("@")[0], origin)
                if target:
                    self._walk_file(target, result, depth + 1)
                return
            if context == "steps" and keys & STEP_KEYS:
                self._step(node, origin, result)
                return
            if node.get("stage") is not None:
                result["stages"] += 1
            if node.get("job") is not None or node.get("deployment") is not None:
                result["jobs"] += 1
            for key, value in node:
                if key == "jobs" and isinstance(value, Pairs):  # GitHub Actions: mapping of job id -> job
                    for job_id, job in value:
                        result["jobs"] += 1
                        uses = job.get("uses") if isinstance(job, Pairs) else None
                        if isinstance(uses, str) and uses.startswith("./"):
                            sibling = origin.rsplit("/", 1)[0] + "/" + uses.rsplit("/", 1)[-1]
                            if sibling in self.files:
                                self._walk_file(sibling, result, depth + 1)
                        self._walk(job, origin, result, depth, None)
                elif key == "steps":
                    self._walk(value, origin, result, depth, "steps")
                else:
                    conditional = isinstance(key, str) and key.strip().startswith("${{")
                    self._walk(value, origin, result, depth, context if conditional else None)
        elif isinstance(node, list):
            for item in node:
                self._walk(item, origin, result, depth, context)

    def _step(self, step: Pairs, origin: str, result: dict) -> None:
        result["steps"] += 1
        uses = step.get("uses")
        if isinstance(uses, str):
            if uses.lower().startswith("azure/login@"):
                result["azure_login_actions"] += 1
            if uses.lower().startswith("actions/checkout@"):
                result["checkouts"] += 1
                settings = step.get("with")
                result["checkout_settings"].append({k: v for k, v in settings} if isinstance(settings, Pairs) else {})
        if step.get("checkout") is not None:
            result["checkouts"] += 1
            result["checkout_settings"].append({k: v for k, v in step if k in ("checkout", "submodules", "fetchDepth", "fetchTags", "clean")})
        texts = []
        for key in ("run", "script", "bash", "pwsh", "powershell"):
            value = step.get(key)
            if isinstance(value, str):
                texts.append(value)
        inputs = step.get("inputs")
        if isinstance(inputs, Pairs):
            for key, value in inputs:
                if isinstance(value, str):
                    if key in ("inlineScript", "script"):
                        texts.append(value)
                    elif key in ("scriptPath", "filePath", "csmFile", "arguments"):
                        resolved = self.resolve(value, origin)
                        if resolved:
                            result["direct_refs"].add(resolved)
                            if resolved.endswith(".bicep"):
                                result["templates"].add(resolved)
                        for ref in self.references(value, origin):
                            result["direct_refs"].add(ref)
        for text in texts:
            add(result["inline"], text_metrics(text))
            for ref in self.references(text, origin):
                result["direct_refs"].add(ref)
                if ref.endswith(".bicep"):
                    result["templates"].add(ref)
            for match in TEMPLATE_FILE.finditer(strip_comments(text)):
                resolved = self.resolve(match.group(1), origin)
                result["templates"].add(resolved or match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("entries", nargs="+")
    args = parser.parse_args()
    analyzer = Analyzer(args.root.resolve())
    report = [analyzer.analyze(entry) for entry in args.entries]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=sorted) + "\n", encoding="utf-8")
    header = ("entry", "files", "stages", "jobs", "steps", "az inline", "az scripts", "waits inline", "wait s inline",
              "waits scripts", "wait s scripts", "var waits", "logins", "acct set", "ext", "deploys", "bicep entries", "scripts")
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for item in report:
        inline, scripts = item["inline"], item["script_metrics"]
        get = lambda d, k: d.get(k, 0)
        row = (item["entry"].rsplit("/", 1)[-1], len(set(item["includes"])), item["stages"], item["jobs"], item["steps"],
               get(inline, "az_calls"), get(scripts, "az_calls"), get(inline, "sleeps"), get(inline, "sleep_seconds"),
               get(scripts, "sleeps"), get(scripts, "sleep_seconds"),
               get(inline, "variable_sleeps") + get(scripts, "variable_sleeps"),
               get(inline, "az_login") + get(scripts, "az_login") + item["azure_login_actions"],
               get(inline, "az_account_set") + get(scripts, "az_account_set"),
               get(inline, "az_extension") + get(scripts, "az_extension") + get(inline, "az_bicep_install") + get(scripts, "az_bicep_install"),
               get(inline, "deployments") + get(scripts, "deployments"),
               len([t for t in item["templates"] if t.endswith(".bicep")]), len(item["scripts"]))
        print("| " + " | ".join(str(v) for v in row) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
