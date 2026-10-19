import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

# Graph outputs are delivered through snapshots/bundles; local generation scratch must never be committed.
IGNORED = (
    ".graph-work-20261016-reuse/aifactory-graph-hmvg292j/result/graphify-out/cache/ast/v0.9.72-s4/0a91.json",
    ".graph-work-20261016-reuse/aifactory-graph-hmvg292j/source/environment_setup/graphify/generate.py",
    ".graph-work-20271231/anything.json",
    "environment_setup/graphify/graphify-out/cache/ast/v0.9.72-s4/0a91.json",
    "graphify-out/graph.json",
)
KEPT = (
    "environment_setup/graphify/generate.py",
    "meta/graphify/.gitignore",
    "documentation/architecture/Index.md",
)


def _ignored(path):
    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=REPO, check=False)
    assert result.returncode in (0, 1), f"git check-ignore failed for {path}"
    return result.returncode == 0


@pytest.mark.parametrize("path", IGNORED)
def test_graph_generation_scratch_is_ignored(path):
    assert _ignored(path)


@pytest.mark.parametrize("path", KEPT)
def test_graph_sources_stay_tracked(path):
    assert not _ignored(path)
