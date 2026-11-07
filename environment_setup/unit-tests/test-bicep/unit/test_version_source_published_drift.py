"""Offline: a checkout at a published descendant or ancestor of the reviewed commit warns, it never blocks.

aif-146..152 deletes (2026-11-07): release/v1.25 moved while jobs were queued and _verify_source refused with
version-source-commit-mismatch, a hard HEAD == published-commit gate. Standing rule (2026-10-30): commit
comparisons warn and the live checks decide; only an unrelated checkout still blocks.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_factory_lifecycle import fl, manifest, workspace, no_real_services  # noqa: F401


def checkout(workspace, head, *, relation, missing_until_fetch=False, published=True):
    source = manifest()["source"]
    commands = []
    fetched = []

    def command(argv, cwd=None):
        commands.append(argv[1:])
        if argv[1:] == ["rev-parse", "--show-toplevel"]:
            return str(workspace)
        if argv[1:] == ["rev-parse", "HEAD"]:
            return head
        if argv[1] == "status":
            return ""
        if argv[1] == "remote":
            return fl.SOURCE_ORIGIN
        if argv[1] == "ls-remote":
            return source["commit"] + "\t" + source["ref"]
        if "fetch" in argv:
            fetched.append(argv)
            return ""
        if argv[1] == "merge-base":
            if missing_until_fetch and not fetched:
                raise fl.Blocked("command-failed")
            if relation == "descendant":
                return source["commit"]
            if relation == "ancestor":
                return head
            raise fl.Blocked("command-failed")
        if argv[1] == "show":
            return Path(fl.__file__).read_text(encoding="utf-8").strip()
        raise AssertionError(argv)

    cloud = SimpleNamespace(command=command, document={})
    return cloud, source, commands, fetched


@pytest.mark.parametrize("relation", ["descendant", "ancestor"])
def test_published_relative_checkout_warns_and_continues(workspace, capsys, relation):
    cloud, source, _, _ = checkout(workspace, "b" * 40, relation=relation)
    assert fl.verify_source(cloud, workspace, source) == workspace
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")]
    drift, = [event for event in events if event["event"] == "version-source-commit-drift"]
    assert drift["checkout_commit"] == "b" * 40 and drift["published_commit"] == source["commit"]


def test_missing_published_commit_is_fetched_before_the_ancestry_check(workspace):
    cloud, source, _, fetched = checkout(workspace, "b" * 40, relation="ancestor", missing_until_fetch=True)
    assert fl.verify_source(cloud, workspace, source) == workspace
    assert fetched and fetched[0][-1] == source["ref"]


def test_accepted_source_tolerates_a_related_checkout_without_network(workspace):
    cloud, source, commands, fetched = checkout(workspace, "b" * 40, relation="descendant")
    assert fl._verify_source(cloud, workspace, source, published=False) == workspace
    assert not fetched and not any(argv[0] == "ls-remote" for argv in commands)


@pytest.mark.parametrize("published", [True, False])
def test_unrelated_checkout_still_blocks(workspace, published):
    cloud, source, _, _ = checkout(workspace, "b" * 40, relation="unrelated")
    with pytest.raises(fl.Blocked, match="version-source-commit-mismatch"):
        fl._verify_source(cloud, workspace, source, published=published)
