#!/usr/bin/env python3
"""Proof c: every `template:` include and every script, Bicep or config path that a kept workflow or pipeline
names resolves on the compacted tree.

A reference counts when it resolved to a file on the BASE tree. It must then exist on the BRANCH tree.
Usage: proof_c.py --base-root DIR --branch-root DIR
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wf_metrics import Analyzer  # noqa: E402

ENTRY_DIRS = (
    ".github/workflows",
    "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions",
    "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops",
    "bootstrap/templates",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--branch-root", type=Path, required=True)
    args = parser.parse_args()
    base = Analyzer(args.base_root.resolve())
    branch_root = args.branch_root.resolve()
    entries = sorted(name for name in base.files
                     if name.startswith(ENTRY_DIRS) and name.endswith((".yml", ".yaml"))
                     and (branch_root / name).is_file())
    checked, missing = 0, []
    for entry in entries:
        report = base.analyze(entry)
        references = set(report["includes"]) | set(report["direct_refs"]) | set(report["scripts"]) | {
            t for t in report["templates"] if t in base.files}
        for reference in sorted(references):
            checked += 1
            if not (branch_root / reference).is_file():
                missing.append((entry, reference))
    dropped_entries = sorted(name for name in base.files
                             if name.startswith(ENTRY_DIRS) and name.endswith((".yml", ".yaml"))
                             and not (branch_root / name).is_file())
    print(f"kept workflow and pipeline files: {len(entries)}; references checked: {checked}; missing: {len(missing)}")
    print(f"workflow and pipeline files not on the branch: {dropped_entries}")
    for entry, reference in missing:
        print(f"  MISSING: {reference}  (named by {entry})")
    return int(bool(missing))


if __name__ == "__main__":
    sys.exit(main())
