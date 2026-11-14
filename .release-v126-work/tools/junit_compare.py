#!/usr/bin/env python3
"""Proof d: every test that passed on the base passes on the branch, or its test file was removed.

Usage: junit_compare.py <base junit.xml> <branch junit.xml> [--branch-root DIR --suite-dir REL]
With --branch-root and --suite-dir, a base test whose file no longer exists under <branch-root>/<suite-dir>
is reported as "removed with its file" instead of "missing".
"""
from __future__ import annotations

import argparse
import collections
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def outcomes(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for case in ET.parse(path).iter("testcase"):
        key = f"{case.get('classname', '')}::{case.get('name', '')}"
        if case.find("failure") is not None:
            state = "failed"
        elif case.find("error") is not None:
            state = "error"
        elif case.find("skipped") is not None:
            state = "skipped"
        else:
            state = "passed"
        # A parametrized id can repeat; the worst outcome wins.
        order = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}
        if key not in result or order[state] > order[result[key]]:
            result[key] = state
    return result


def test_file(key: str) -> str:
    classname = key.split("::", 1)[0]
    parts = classname.split(".")
    # pytest classnames: "unit.test_x" or "unit.test_x.TestClass" or "test_x"
    module = [p for p in parts if not p[:1].isupper()]
    return "/".join(module) + ".py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("branch", type=Path)
    parser.add_argument("--branch-root", type=Path)
    parser.add_argument("--suite-dir", default="")
    parser.add_argument("--show", type=int, default=40)
    args = parser.parse_args()
    base, branch = outcomes(args.base), outcomes(args.branch)
    count = lambda data: dict(collections.Counter(data.values()))
    print(f"base:   {len(base)} tests {count(base)}")
    print(f"branch: {len(branch)} tests {count(branch)}")
    regressions, removed, missing = [], [], []
    for key, state in base.items():
        if state != "passed":
            continue
        now = branch.get(key)
        if now == "passed":
            continue
        if now is None:
            relative = test_file(key)
            gone = args.branch_root is not None and not (args.branch_root / args.suite_dir / relative).is_file()
            (removed if gone else missing).append((key, relative))
        else:
            regressions.append((key, now))
    newly = [(k, s) for k, s in branch.items() if k not in base]
    still_failing = [(k, s) for k, s in branch.items() if s in ("failed", "error") and base.get(k) in ("failed", "error")]
    fixed = [k for k, s in branch.items() if s == "passed" and base.get(k) in ("failed", "error")]
    print(f"passed on base, not passed on branch: {len(regressions)}")
    print(f"passed on base, test file removed on branch: {len(removed)} tests in "
          f"{len({f for _, f in removed})} files")
    print(f"passed on base, missing on branch (file still there): {len(missing)}")
    print(f"failing on both: {len(still_failing)}; failing on base and passing on branch: {len(fixed)}; "
          f"new on branch: {len(newly)} {dict(collections.Counter(s for _, s in newly))}")
    for label, items in (("REGRESSION", regressions), ("MISSING", missing)):
        for key, extra in items[: args.show]:
            print(f"  {label}: {key} -> {extra}")
    for relative, number in collections.Counter(f for _, f in removed).most_common(args.show):
        print(f"  REMOVED FILE: {relative} ({number} tests)")
    return int(bool(regressions or missing))


if __name__ == "__main__":
    sys.exit(main())
