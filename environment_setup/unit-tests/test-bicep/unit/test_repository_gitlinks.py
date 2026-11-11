"""Guard: the accelerator tracks no gitlink that .gitmodules does not declare.

Consumers check this repository out as a submodule with ``git submodule update --init --recursive``
(the Azure DevOps ``checkout: self, submodules: recursive`` step). An undeclared gitlink, such as a
Claude Code worktree under ``.claude/worktrees/`` committed by ``git add -A``, stops that checkout with
"No url found for submodule path" before any pipeline step runs (Spider Add-Factory-Agent run 2401).
Offline: reads ``git ls-files`` and ``.gitignore`` only.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def tracked_gitlinks():
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-s", "-z"], check=True, capture_output=True
    ).stdout
    for entry in filter(None, listing.decode("utf-8").split("\0")):
        metadata, path = entry.split("\t", 1)  # "<mode> <object> <stage>\t<path>"
        if metadata.startswith("160000 "):
            yield path


def declared_submodules():
    gitmodules = ROOT / ".gitmodules"
    if not gitmodules.is_file():
        return set()
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "config", "-f", str(gitmodules), "--get-regexp", r"^submodule\..*\.path$"],
        capture_output=True,
    ).stdout.decode("utf-8")
    return {line.split(" ", 1)[1].strip() for line in listing.splitlines() if " " in line}


def test_every_gitlink_is_a_declared_submodule():
    undeclared = sorted(set(tracked_gitlinks()) - declared_submodules())
    assert not undeclared, f"Undeclared gitlinks break recursive submodule checkouts: {undeclared}"


def test_claude_worktrees_are_ignored():
    lines = {line.strip() for line in (ROOT / ".gitignore").read_text("utf-8").splitlines()}
    assert ".claude/worktrees/" in lines
