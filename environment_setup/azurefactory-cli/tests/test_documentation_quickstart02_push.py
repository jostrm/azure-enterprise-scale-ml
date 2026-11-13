"""Quickstart 02 pushes the consumer repository before the Factory Init (video 10, 2026-11-13).

The pipelines read the repository from GitHub or Azure DevOps, not from the reader's computer. The page said
"Commit and push it" only after the run, so a fresh repository started Init without the submodule and folder.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = Path(os.environ.get("ESAF_QUICKSTART02", ROOT / "documentation" / "v2" / "quickstarts" / "02-create-factory.md"))


def section(text: str, heading: str) -> str:
    start = text.index("\n## " + heading + "\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end > 0 else len(text)]


def test_create_section_commits_and_pushes_before_any_tool_runs_init():
    create = section(PAGE.read_text(encoding="utf-8"), "Create the Factory")
    first_tool = create.index("<details")
    steps = [create.index(command) for command in ("git status", "git add --all", "git commit -m", "git push")]
    assert steps == sorted(steps) and steps[-1] < first_tool
    assert steps[-1] < create.index("azurefactory esaf init-factory")


def test_push_step_says_why_and_warns_about_secrets():
    create = section(PAGE.read_text(encoding="utf-8"), "Create the Factory")
    push = create[:create.index("<details")]
    assert "pipelines" in push and "GitHub" in push and "Azure DevOps" in push
    assert "secret" in push.lower()
