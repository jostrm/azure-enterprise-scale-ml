"""Offline contract: no Azure DevOps pipeline template checks out full git history.

``fetchDepth: 0`` makes every job download the whole history of the consumer repository and, because the same
depth is used for ``git submodule update``, the whole history of the AI Factory submodule (GitHub reports about
2.4 GB for it). No step in these pipelines reads history: they use the files of one commit. With
``fetchDepth: 1`` a job fetches one commit of each. The lifecycle worker, the one place that needs ancestry,
deepens a shallow checkout by itself (``verify_consent_ancestors`` in ``bootstrap/lib/factory_lifecycle.py``).
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[4]
ADO = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines"
GHA = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions"
TEMPLATES = ROOT / "bootstrap/templates"

# Jobs that used to ask for full history; each must now ask for one commit explicitly, so that the setting
# does not depend on the "shallow fetch" switch of the consumer's pipeline definition.
EXPLICITLY_SHALLOW = {
    "esml-infra-project/infra-project-genai.yaml": 9,
    "aifactory-governance/gov-cross-charging.yaml": 3,
    "esml-infra-project/jobs/stage-private-azure-mcp.yaml": 1,
    "esml-infra-project/add-factory-agent.yaml": 1,
}
# Git commands that need more than the checked-out commit. `git log -1` and `git log --oneline -1` do not.
HISTORY_COMMAND = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?(?:describe|rev-list|merge-base|blame|shortlog|bisect|cherry|log(?!\s+(?:--oneline\s+)?-(?:1|n\s*1)\b))")


def ado_files() -> list[Path]:
    files = sorted(ADO.rglob("*.yaml")) + sorted(ADO.rglob("*.yml")) + sorted(TEMPLATES.glob("*-ado.yml"))
    assert len(files) >= 25, "the Azure DevOps pipeline templates moved"
    return files


def checkout_blocks(text: str) -> list[str]:
    """Each `- checkout:` step with the keys that belong to it."""
    lines = text.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)-\s+checkout:\s*\S+", line)
        if not match:
            continue
        indent = len(match.group(1))
        block = [line]
        for following in lines[index + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            block.append(following)
        blocks.append("\n".join(block))
    return blocks


def fetch_depth(block: str) -> int | None:
    match = re.search(r"^\s*fetchDepth:\s*(\d+)", block, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


@pytest.mark.parametrize("path", ado_files(), ids=lambda p: p.name)
def test_no_checkout_asks_for_full_history(path):
    for block in checkout_blocks(path.read_text(encoding="utf-8")):
        assert fetch_depth(block) != 0, f"{path.name}: `fetchDepth: 0` downloads all history in every job:\n{block}"


@pytest.mark.parametrize("relative, expected", sorted(EXPLICITLY_SHALLOW.items()))
def test_jobs_with_the_submodule_fetch_one_commit(relative, expected):
    blocks = checkout_blocks((ADO / relative).read_text(encoding="utf-8"))
    with_submodule = [block for block in blocks if re.search(r"^\s*submodules:\s*(?:recursive|true)\b", block, re.MULTILINE)]
    assert len(with_submodule) == expected, f"{relative}: expected {expected} checkouts with the submodule"
    for block in with_submodule:
        assert fetch_depth(block) == 1, f"{relative}: the checkout must state `fetchDepth: 1`:\n{block}"


@pytest.mark.parametrize("path", ado_files() + sorted(GHA.glob("*.yml")), ids=lambda p: p.name)
def test_no_pipeline_step_reads_git_history(path):
    """A shallow checkout is only safe while no step needs older commits; this fails when one appears."""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        assert not HISTORY_COMMAND.search(line), (
            f"{path.name}:{number} reads git history; with a depth-1 checkout it must deepen first: {line.strip()}")


def test_github_workflows_keep_the_default_depth_of_one():
    """actions/checkout fetches one commit unless `fetch-depth` says otherwise."""
    for path in sorted(GHA.glob("*.yml")) + sorted(TEMPLATES.glob("*-gha.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = re.match(r"^\s*fetch-depth:\s*(\d+)", line)
            assert not match or int(match.group(1)) == 1, f"{path.name}:{number} asks for more than one commit"
