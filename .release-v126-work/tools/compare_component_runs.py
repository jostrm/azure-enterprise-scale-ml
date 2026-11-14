#!/usr/bin/env python3
"""Compare two result folders of run_component_suites.py (stdlib only).

    compare_component_runs.py <before-results> <after-results> [--label-before X] [--label-after Y] [--out file.md]

Per suite: the counters of both runs.  Per test that failed or errored in at least one of the two runs:
its outcome in each run (passed / failed / error / skipped / absent), taken from the junit.xml files.
Works for "without wrapper vs. with wrapper" on one worktree and for "base vs. branch" on two worktrees.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RANK = {"error": 4, "failed": 3, "skipped": 2, "passed": 1}


def outcomes(junit):
    result, reasons = {}, {}
    if not junit.is_file():
        return result, reasons
    try:
        root = ET.parse(junit).getroot()
    except ET.ParseError:
        return result, reasons
    for case in root.iter("testcase"):
        key = (case.get("classname", "") + "::" + case.get("name", "")).lstrip(":")
        tags = {child.tag: child for child in case}
        if "error" in tags:
            status, node = "error", tags["error"]
        elif "failure" in tags:
            status, node = "failed", tags["failure"]
        elif "skipped" in tags:
            status, node = "skipped", tags["skipped"]
        else:
            status, node = "passed", None
        if RANK[status] >= RANK.get(result.get(key, ""), 0):
            result[key] = status
            if node is not None:
                text = (node.get("message") or node.text or "").strip().splitlines()
                reasons[key] = (text[0] if text else "")[:220]
    return result, reasons


def load(folder):
    path = folder / "summary.json"
    return {e["id"]: e for e in json.loads(path.read_text(encoding="utf-8"))["suites"]} if path.is_file() else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--label-before", default="before")
    parser.add_argument("--label-after", default="after")
    parser.add_argument("--out")
    args = parser.parse_args()
    before_dir, after_dir = Path(args.before), Path(args.after)
    before, after = load(before_dir), load(after_dir)
    a, b = args.label_before, args.label_after
    lines = ["# Component suites: %s vs. %s" % (a, b), "",
             "- %s: `%s`" % (a, before_dir), "- %s: `%s`" % (b, after_dir), "",
             "| suite | status %s | status %s | tests | passed | failed | errors | skipped |" % (a, b),
             "|---|---|---|---|---|---|---|---|"]
    ids = [i for i in after] + [i for i in before if i not in after]
    for suite in ids:
        x, y = before.get(suite, {}), after.get(suite, {})
        cell = lambda k: "%s -> %s" % (x.get(k, "-"), y.get(k, "-"))
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            suite, x.get("status", "-"), y.get("status", "-"), cell("tests"), cell("passed"), cell("failed"),
            cell("errors"), cell("skipped")))
    lines += ["", "## Tests that failed or errored in at least one run", ""]
    totals = {}
    for suite in ids:
        old, old_reason = outcomes(before_dir / suite / "junit.xml")
        new, new_reason = outcomes(after_dir / suite / "junit.xml")
        bad = sorted(k for k in set(old) | set(new) if old.get(k) in ("failed", "error") or new.get(k) in ("failed", "error"))
        if not bad:
            continue
        lines += ["### %s" % suite, "", "| test | %s | %s | reason (%s, else %s) |" % (a, b, b, a), "|---|---|---|---|"]
        for key in bad:
            o, n = old.get(key, "absent"), new.get(key, "absent")
            totals[(o, n)] = totals.get((o, n), 0) + 1
            reason = (new_reason.get(key) or old_reason.get(key) or "").replace("|", "\\|")
            lines.append("| `%s` | %s | %s | %s |" % (key, o, n, reason))
        lines.append("")
    lines += ["## Transition counts (%s -> %s)" % (a, b), ""]
    for (o, n), count in sorted(totals.items(), key=lambda item: -item[1]):
        lines.append("- %s -> %s: %d" % (o, n, count))
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
