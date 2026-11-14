"""Offline contract: the commands RELEASE_126.md gives for getting this branch as a small submodule work.

``git submodule add -b <branch> --depth 1 <url>`` works only for the remote's default branch. The shallow clone
it makes is single-branch, so ``origin/<branch>`` does not exist for any other branch: git downloads the default
branch first and then stops with "is not a commit and a branch cannot be created from it" (git 2.43).
``release/v1.26`` is not the default branch, so the release note gives commands that work, in two blocks:

* adding the submodule to a repository (clone the branch, then register the clone);
* getting it in a fresh clone of that repository without downloading the default branch (fetch the pinned commit).

This test runs both blocks against a local repository of the same shape: a default branch ``main`` that holds a
file the release branch dropped, and the branch ``release/v1.26``.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
RELEASE_NOTE = ROOT / "RELEASE_126.md"
BRANCH = "release/v1.26"
PUBLIC_URL = "https://github.com/jostrm/azure-enterprise-scale-ml"
SUBMODULE = "azure-enterprise-scale-ml"
VERSION_LIBRARY = ROOT / "bootstrap/lib/release_version.sh"


def documented_block(marker: str) -> list[str]:
    """The command lines of the fenced bash block in the note that contains `marker`."""
    text = RELEASE_NOTE.read_text(encoding="utf-8")
    for block in re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL):
        if marker in block:
            lines = [line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("#")]
            assert any(PUBLIC_URL in line for line in lines), "the block must name the public repository URL"
            return lines
    pytest.fail(f"RELEASE_126.md has no bash block with `{marker}`")


def bash_executable() -> str | None:
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    return str(git_bash) if git_bash.is_file() else shutil.which("bash")


def git_environment(tmp_path: Path) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME="Offline fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
        GIT_COMMITTER_NAME="Offline fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid",
        # The fixture remote is a local folder; git only clones submodules from file:// when told to.
        GIT_CONFIG_COUNT="3",
        GIT_CONFIG_KEY_0="protocol.file.allow", GIT_CONFIG_VALUE_0="always",
        GIT_CONFIG_KEY_1="commit.gpgsign", GIT_CONFIG_VALUE_1="false",
        GIT_CONFIG_KEY_2="core.autocrlf", GIT_CONFIG_VALUE_2="false",
        HOME=str(tmp_path))
    return environment


def git(directory: Path, environment: dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True,
                            env=environment, timeout=120)
    if check and result.returncode:
        pytest.fail(f"git {' '.join(args)} in {directory} failed: {result.stderr.strip()}")
    return result


def commit_on_release_branch(remote: Path, environment: dict[str, str], name: str) -> str:
    git(remote, environment, "checkout", BRANCH)
    (remote / name).write_text(name + "\n", encoding="utf-8")
    git(remote, environment, "add", ".")
    git(remote, environment, "commit", "-m", name)
    commit = git(remote, environment, "rev-parse", "HEAD").stdout.strip()
    git(remote, environment, "checkout", "main")
    return commit


@pytest.fixture
def upstream(tmp_path: Path) -> tuple[Path, dict[str, str], str, str]:
    """A remote with a default branch `main` and a second branch `release/v1.26`, as on GitHub."""
    environment = git_environment(tmp_path)
    remote = tmp_path / "upstream"
    remote.mkdir()
    git(remote, environment, "init", "--initial-branch=main")
    (remote / "only-on-main.bin").write_text("large installer that the mini release dropped\n", encoding="utf-8")
    (remote / "01-start-v125-and-above.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    git(remote, environment, "add", ".")
    git(remote, environment, "commit", "-m", "main")
    main_tip = git(remote, environment, "rev-parse", "HEAD").stdout.strip()
    git(remote, environment, "checkout", "-b", BRANCH)
    git(remote, environment, "rm", "-q", "only-on-main.bin")
    git(remote, environment, "commit", "-m", "mini release")
    release_tip = git(remote, environment, "rev-parse", "HEAD").stdout.strip()
    git(remote, environment, "checkout", "main")
    return remote, environment, main_tip, release_tip


def add_submodule_as_documented(consumer: Path, environment: dict[str, str], remote: Path) -> Path:
    consumer.mkdir()
    git(consumer, environment, "init", "--initial-branch=main")
    for command in documented_block("submodule add"):
        arguments = shlex.split(command.replace(PUBLIC_URL, remote.as_uri()))
        assert arguments[0] == "git", f"the recipe is plain git commands, got: {command}"
        git(consumer, environment, *arguments[1:])
    return consumer / SUBMODULE


def test_the_note_does_not_give_the_one_command_form_that_fails():
    for command in documented_block("submodule add"):
        assert not re.search(r"\bsubmodule\s+add\b.*--depth\b", command), (
            "`git submodule add -b release/v1.26 --depth 1` fails for a branch that is not the default: " + command)


def test_the_one_command_form_really_fails_for_a_non_default_branch(upstream, tmp_path):
    """Pins the git behavior the note works around; if git ever fixes it, the note can become one line."""
    remote, environment, _, _ = upstream
    consumer = tmp_path / "consumer-one-command"
    consumer.mkdir()
    git(consumer, environment, "init", "--initial-branch=main")
    result = git(consumer, environment, "submodule", "add", "-b", BRANCH, "--depth", "1", remote.as_uri(),
                 SUBMODULE, check=False)
    if result.returncode == 0:
        pytest.skip("this git adds a shallow submodule on a non-default branch in one command")
    assert "is not a commit" in result.stderr or "unable to checkout submodule" in result.stderr, result.stderr


def test_the_documented_commands_add_a_shallow_submodule_on_the_release_branch(upstream, tmp_path):
    remote, environment, main_tip, release_tip = upstream
    consumer = tmp_path / "consumer"
    submodule = add_submodule_as_documented(consumer, environment, remote)

    assert git(submodule, environment, "rev-parse", "HEAD").stdout.strip() == release_tip
    assert git(submodule, environment, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    # The default branch was not downloaded: that is the point of the mini release.
    assert git(submodule, environment, "cat-file", "-e", main_tip, check=False).returncode != 0
    assert not (submodule / "only-on-main.bin").exists()
    # A normal submodule: git directory inside the consumer's .git, the branch recorded, everything staged.
    assert (submodule / ".git").is_file(), "the submodule's git directory must be absorbed into the consumer"
    settings = git(consumer, environment, "config", "-f", ".gitmodules", "--list").stdout
    assert f"submodule.{SUBMODULE}.branch={BRANCH}" in settings
    assert git(consumer, environment, "status", "--porcelain").stdout.strip().splitlines() == [
        "A  .gitmodules", f"A  {SUBMODULE}"], "nothing may be left unstaged after the recipe"


def test_a_fresh_clone_gets_the_pinned_commit_without_the_default_branch(upstream, tmp_path):
    """The second block: what a colleague or a pipeline job runs instead of `git submodule update --init`."""
    bash = bash_executable()
    if not bash:
        pytest.skip("Bash required")
    remote, environment, main_tip, pinned = upstream
    consumer = tmp_path / "consumer"
    add_submodule_as_documented(consumer, environment, remote)
    git(consumer, environment, "commit", "-m", "Add the AI Factory submodule")
    # The branch moves on after the consumer pinned its commit: the fresh clone must still get the pinned one.
    newer = commit_on_release_branch(remote, environment, "published-later.txt")

    colleague = tmp_path / "colleague"
    git(tmp_path, environment, "clone", "--quiet", str(consumer), str(colleague))
    script = "set -euo pipefail\n" + "\n".join(documented_block("FETCH_HEAD")).replace(PUBLIC_URL, remote.as_uri()) + "\n"
    result = subprocess.run([bash, "--noprofile", "--norc", "-c", script], capture_output=True, text=True,
                            timeout=120, env=environment, cwd=colleague)
    assert result.returncode == 0, result.stdout + result.stderr

    submodule = colleague / SUBMODULE
    assert git(submodule, environment, "rev-parse", "HEAD").stdout.strip() == pinned
    for not_downloaded in (main_tip, newer):
        assert git(submodule, environment, "cat-file", "-e", not_downloaded, check=False).returncode != 0
    assert not (submodule / "only-on-main.bin").exists() and not (submodule / "published-later.txt").exists()
    assert (submodule / ".git").is_file(), "the submodule's git directory must be absorbed into the clone"
    assert git(colleague, environment, "status", "--porcelain").stdout.strip() == ""
    assert git(colleague, environment, "submodule", "status").stdout.startswith(" " + pinned)


def test_the_update_launchers_fast_forward_the_shallow_submodule(upstream, tmp_path):
    """An ordinary update fetches the branch and proves the fast-forward by ancestry (bootstrap/lib/release_version.sh).

    That proof needs the history between the old and the new commit, so it has to work in the shallow clone
    the documented commands make.
    """
    bash = bash_executable()
    if not bash:
        pytest.skip("Bash required")
    remote, environment, _, release_tip = upstream
    consumer = tmp_path / "consumer"
    submodule = add_submodule_as_documented(consumer, environment, remote)
    assert git(submodule, environment, "rev-parse", "HEAD").stdout.strip() == release_tip
    latest = commit_on_release_branch(remote, environment, "published-later.txt")

    script = (
        f"set -euo pipefail\nsource {shlex.quote(VERSION_LIBRARY.as_posix())}\n"
        'AIF_SUBMODULE_BRANCH="$TEST_BRANCH"\nAIF_SUBMODULE_REF="$TEST_COMMIT"\n'
        'export AIFACTORY_VERSION=126 AIF_SUBMODULE_BRANCH AIF_SUBMODULE_REF\n'
        "AIF_VERSION_KEEP_DETACHED=false\n"
        'AIF_VERSION_PYTHON=("$TEST_PYTHON")\n'
        'aif_version_checkout "$TEST_ROOT"\n'
    )
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-c", script], capture_output=True, text=True, timeout=120,
        env={**environment, "TEST_ROOT": consumer.as_posix(), "TEST_BRANCH": BRANCH, "TEST_COMMIT": latest,
             "TEST_PYTHON": Path(sys.executable).as_posix()})
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(submodule, environment, "rev-parse", "HEAD").stdout.strip() == latest
    assert git(submodule, environment, "branch", "--show-current").stdout.strip() == BRANCH
    assert git(submodule, environment, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    assert (submodule / "published-later.txt").is_file()
