#!/usr/bin/env python3
"""Build Bicep files to ARM JSON and report metrics plus a normalized hash (proof b).

The normalized hash ignores the generator metadata (`metadata._generator`) and every `templateHash`, at any depth,
so two trees compare equal when the compiled templates are the same.

Usage: bicep_metrics.py --root <repo root> --out <dir> [--jobs N] [--list FILE | paths...]
       bicep_metrics.py --compare <base.json> <other.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BICEP = "/home/user/tools/bicep/bicep"


def normalize(node):
    if isinstance(node, dict):
        cleaned = {}
        for key, value in node.items():
            if key == "templateHash":
                continue
            if key == "_generator":
                continue
            cleaned[key] = normalize(value)
        return cleaned
    if isinstance(node, list):
        return [normalize(item) for item in node]
    return node


def count(template: dict) -> tuple[int, int]:
    """(resources, nested deployments), recursing into nested inline templates."""
    resources, nested = 0, 0
    items = template.get("resources", [])
    if isinstance(items, dict):  # symbolic-name templates (languageVersion 2.0)
        items = list(items.values())
    for item in items:
        if not isinstance(item, dict):
            continue
        resources += 1
        if str(item.get("type", "")).lower() == "microsoft.resources/deployments":
            nested += 1
            inner = item.get("properties", {}).get("template")
            if isinstance(inner, dict):
                more_resources, more_nested = count(inner)
                resources += more_resources
                nested += more_nested
    return resources, nested


def build(root: Path, relative: str, out: Path) -> dict:
    target = out / (relative.replace("/", "__") + ".json")
    started = time.monotonic()
    result = subprocess.run([BICEP, "build", str(root / relative), "--outfile", str(target)],
                            capture_output=True, text=True, timeout=900)
    seconds = round(time.monotonic() - started, 2)
    record = {"path": relative, "seconds": seconds, "exit": result.returncode,
              "warnings": result.stderr.count(" Warning "), "errors": result.stderr.count(" Error ")}
    if result.returncode != 0 or not target.is_file():
        record["stderr"] = result.stderr.strip()[-2000:]
        return record
    raw = target.read_bytes()
    template = json.loads(raw)
    resources, nested = count(template)
    normalized = json.dumps(normalize(template), sort_keys=True, separators=(",", ":")).encode()
    record.update({"bytes": len(raw), "resources": resources, "nested_deployments": nested,
                   "normalized_sha256": hashlib.sha256(normalized).hexdigest()})
    return record


def compare(base_file: Path, other_file: Path) -> int:
    base = {r["path"]: r for r in json.loads(base_file.read_text())}
    other = {r["path"]: r for r in json.loads(other_file.read_text())}
    different, missing_base, failed = [], [], []
    for path, record in sorted(other.items()):
        if path not in base:
            missing_base.append(path)
        elif record.get("exit") != 0:
            failed.append(path)
        elif record.get("normalized_sha256") != base[path].get("normalized_sha256"):
            different.append(path)
    print(f"compared {len(other)} files: {len(different)} differ, {len(failed)} failed to build, "
          f"{len(missing_base)} not in the base report, {len(set(base) - set(other))} only in the base report")
    for label, items in (("DIFFERENT", different), ("FAILED", failed), ("NOT IN BASE", missing_base)):
        for item in items:
            print(f"  {label}: {item}")
    return int(bool(different or failed))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--list", type=Path)
    parser.add_argument("--compare", nargs=2, type=Path)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    if args.compare:
        return compare(*args.compare)
    paths = list(args.paths)
    if args.list:
        paths += [line.strip() for line in args.list.read_text().splitlines() if line.strip()]
    args.out.mkdir(parents=True, exist_ok=True)
    arm = args.out / "arm"
    arm.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(lambda p: build(args.root.resolve(), p, arm), paths))
    (args.out / "bicep-metrics.json").write_text(json.dumps(records, indent=1) + "\n")
    failed = [r for r in records if r["exit"] != 0]
    print(f"built {len(records) - len(failed)} of {len(records)}; failed: {len(failed)}")
    for record in failed:
        print("  FAILED", record["path"], "::", record.get("stderr", "")[:300].replace("\n", " | "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
