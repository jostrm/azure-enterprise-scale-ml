"""Guard: the v1.25 release branch is spelled release/v1.25 in every tracked text file.

The misspelled branch (a dot between "v" and "1") was retired on 2026-10-24. Scripts,
pipelines, workflows and documentation must name ``release/v1.25``, the branch that
``bootstrap/lib/release_version.py`` derives for ``--aifactory-version 125``.
Offline: reads ``git ls-files`` and file bytes only.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
# Built from parts so this guard never matches its own source text.
RETIRED_SPELLING = re.compile(rb"(?<![\w.])v" + rb"\.1\.25(?!\d)")


def tracked_text_files():
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    for name in filter(None, listing.decode("utf-8").split("\0")):
        try:
            data = (ROOT / name).read_bytes()
        except OSError:  # submodule gitlinks, sparse or deleted paths
            continue
        if b"\0" not in data[:8192]:
            yield name, data


def test_retired_spelling_pattern_matches_only_the_dotted_form():
    assert RETIRED_SPELLING.search(b"release/v." + b"1.25")
    assert RETIRED_SPELLING.search(b"(v." + b"1.25 and higher)")
    for allowed in (b"release/v1.25", b"v1.25", b"v.1.250", b"nv.1.25", b"1.v.1.25"):
        assert not RETIRED_SPELLING.search(allowed), allowed


def test_no_tracked_text_file_names_the_retired_v125_branch_spelling():
    newline = b"\n"
    offenders = sorted(
        f"{name}:{data.count(newline, 0, match.start()) + 1}"
        for name, data in tracked_text_files()
        for match in RETIRED_SPELLING.finditer(data)
    )
    assert offenders == [], "use release/v1.25 instead of the retired spelling in: " + ", ".join(offenders)
