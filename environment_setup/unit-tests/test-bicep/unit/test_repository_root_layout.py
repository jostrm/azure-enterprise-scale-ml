"""Guard: the repository root stays small: at most four folders and four Markdown files.

The root is the first page a reader sees on GitHub. Everything else lives one level down:
components under ``usecase_code/``, older release notes under ``documentation/releases/`` and the
community files under ``.github/``. ``.github`` and ``.claude`` do not count, because GitHub and
Claude Code only read them at the root. Offline: reads ``git ls-files`` only, so local scratch
folders (a virtual environment, test caches, a generated graph) do not matter.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

FOLDERS = {"bootstrap", "documentation", "environment_setup", "usecase_code"}
TOOL_FOLDERS = {".github", ".claude"}
MARKDOWN = {"README.md", "RELEASE_126.md", "AGENTS.md", "CLAUDE.md"}


def tracked_root_entries() -> tuple[set[str], set[str]]:
    """Return the tracked folders and the tracked files directly under the repository root."""
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], check=True, capture_output=True
    ).stdout.decode("utf-8")
    folders, files = set(), set()
    for path in filter(None, listing.split("\0")):
        head, separator, _ = path.partition("/")
        (folders if separator else files).add(head)
    return folders, files


def test_root_folders_are_the_four_agreed_ones():
    folders, _ = tracked_root_entries()
    extra = sorted(folders - FOLDERS - TOOL_FOLDERS)
    assert not extra, (
        f"Move these folders below one of {sorted(FOLDERS)} (see 'Moved paths' in RELEASE_126.md): {extra}"
    )
    assert len(folders - TOOL_FOLDERS) <= 4


def test_root_markdown_files_are_the_four_agreed_ones():
    _, files = tracked_root_entries()
    markdown = {name for name in files if name.lower().endswith(".md")}
    extra = sorted(markdown - MARKDOWN)
    assert not extra, (
        "Move these files to documentation/releases/ (release notes, roadmap) or .github/ "
        f"(community files): {extra}"
    )
    assert len(markdown) <= 4
