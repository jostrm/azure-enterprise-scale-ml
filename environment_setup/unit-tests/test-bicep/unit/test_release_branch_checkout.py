"""Offline Git repositories exercise the actual ordinary-update checkout helper."""

import os
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[4]
LIBRARY = ROOT / "bootstrap/lib/release_version.sh"


@pytest.fixture
def repositories(tmp_path):
    def git(root, *args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                                text=True, check=True, timeout=20)
        return result.stdout.strip()

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-b", "main")
    git(seed, "config", "user.name", "Offline Test")
    git(seed, "config", "user.email", "test@example.invalid")
    git(seed, "config", "commit.gpgsign", "false")
    (seed / "first.txt").write_text("one\n")
    git(seed, "add", "first.txt")
    git(seed, "commit", "-m", "first")
    first = git(seed, "rev-parse", "HEAD")
    git(seed, "branch", "release/v1.24")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "origin", "main", "release/v1.24")
    root = tmp_path / "consumer"
    root.mkdir()
    source = root / "azure-enterprise-scale-ml"
    subprocess.run(["git", "clone", "--branch", "main", str(origin), str(source)],
                   check=True, capture_output=True)
    git(source, "config", "user.name", "Offline Test")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "commit.gpgsign", "false")

    def advance(branch):
        git(seed, "checkout", branch)
        (seed / "next.txt").write_text(branch + "\n" + git(seed, "rev-parse", "HEAD") + "\n")
        git(seed, "add", "next.txt")
        git(seed, "commit", "-m", "next")
        git(seed, "push", "origin", branch)
        return git(seed, "rev-parse", "HEAD")

    return git, root, source, seed, first, advance


def checkout(root, branch, commit, *, detached=False, save=False):
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash required")
    script = (
        f"set -euo pipefail\nsource {shlex.quote(LIBRARY.as_posix())}\n"
        'AIF_SUBMODULE_BRANCH="$TEST_BRANCH"\nAIF_SUBMODULE_REF="$TEST_COMMIT"\n'
        'export AIFACTORY_VERSION="$TEST_VERSION" AIF_SUBMODULE_BRANCH AIF_SUBMODULE_REF\n'
        'AIF_VERSION_KEEP_DETACHED="$TEST_DETACHED"\n'
        'AIF_VERSION_PYTHON=("$TEST_PYTHON")\n'
        'aif_version_checkout "$TEST_ROOT"\n'
        + ('aif_version_save "$TEST_ROOT"\n' if save else "")
    )
    return subprocess.run(
        [bash, "--noprofile", "--norc", "-c", script], capture_output=True, text=True, timeout=30,
        env={**os.environ, "TEST_ROOT": root.as_posix(), "TEST_BRANCH": branch,
             "TEST_VERSION": "main" if branch == "main" else "124", "TEST_COMMIT": commit,
             "TEST_DETACHED": str(detached).lower(), "TEST_PYTHON": Path(sys.executable).as_posix()},
    )


@pytest.mark.parametrize("branch", ["main", "release/v1.24"])
@pytest.mark.parametrize("existing", [False, True])
def test_ordinary_update_attaches_and_fast_forwards_selected_branch(repositories, branch, existing):
    git, root, source, _, first, advance = repositories
    if existing and branch != "main":
        git(source, "branch", branch, first)
    git(source, "checkout", "--detach", first)
    latest = advance(branch)
    result = checkout(root, branch, latest, save=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(source, "branch", "--show-current") == branch
    assert git(source, "rev-parse", "HEAD") == latest
    assert git(source, "rev-parse", "--abbrev-ref", "@{upstream}") == "origin/" + branch
    record = json.loads((root / "aifactory/config-wizard/aifactory-version.json").read_text())
    assert record["resolved_ref"] == latest and record["branch"] == branch
    assert git(source, "status", "--porcelain") == ""
    next_commit = advance(branch)
    git(source, "pull", "--ff-only")
    assert git(source, "rev-parse", "HEAD") == next_commit
    assert git(source, "branch", "--show-current") == branch


@pytest.mark.parametrize("scenario", ["ahead", "diverged", "dirty", "remote-moved"])
def test_update_refuses_to_discard_local_work_or_change_selected_commit(repositories, scenario):
    git, root, source, _, first, advance = repositories
    branch = "release/v1.24"
    git(source, "checkout", "-b", branch, first)
    if scenario in {"ahead", "diverged"}:
        (source / "local.txt").write_text("keep\n")
        git(source, "add", "local.txt")
        git(source, "commit", "-m", "local")
    branch_before = git(source, "rev-parse", branch)
    expected = advance(branch) if scenario in {"diverged", "remote-moved"} else first
    if scenario == "dirty":
        (source / "local.txt").write_text("untracked keep\n")
    selected = first if scenario == "remote-moved" else expected
    result = checkout(root, branch, selected)
    assert result.returncode != 0
    assert git(source, "rev-parse", branch) == branch_before
    assert git(source, "rev-parse", "HEAD") == branch_before
    assert not (root / "aifactory/config-wizard/aifactory-version.json").exists()
    if scenario != "remote-moved":
        assert (source / "local.txt").read_text() in {"keep\n", "untracked keep\n"}


def test_explicit_pin_stays_detached_and_does_not_rewind_local_branch(repositories):
    git, root, source, _, first, advance = repositories
    latest = advance("main")
    git(source, "fetch", "origin", "main")
    git(source, "merge", "--ff-only", latest)
    result = checkout(root, "main", first, detached=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(source, "branch", "--show-current") == ""
    assert git(source, "rev-parse", "HEAD") == first
    assert git(source, "rev-parse", "main") == latest


@pytest.mark.parametrize("pin,reviewed,project_only,expected", [
    (False, False, False, "false"), (True, False, False, "true"),
    (False, True, False, "true"), (False, False, True, "true"),
])
def test_prepare_captures_pin_intent_before_resolver_exports_a_sha(
        tmp_path, pin, reviewed, project_only, expected):
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    executable = str(bash) if bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash required")
    script = (
        f"set -euo pipefail\nsource {shlex.quote(LIBRARY.as_posix())}\n"
        'python() { if [[ "${1:-}" == --version ]]; then printf "Python 3\\n"; else\n'
        'printf "export AIFACTORY_VERSION=124 AIF_SUBMODULE_BRANCH=release/v1.24 AIF_SUBMODULE_REF=%s\\n" "$TEST_SHA"; fi; }\n'
        'aif_version_prepare "$TEST_ROOT" "$TEST_PROJECT_ONLY" true ""\n'
        'printf "MODE:%s\\n" "$AIF_VERSION_KEEP_DETACHED"\n'
    )
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AIFACTORY_VERSION", "AIF_SUBMODULE_"))}
    env.update(TEST_ROOT=tmp_path.as_posix(), TEST_SHA="a" * 40,
               TEST_PROJECT_ONLY=str(project_only).lower())
    if pin:
        env["AIF_SUBMODULE_REF"] = "a" * 40
    if reviewed:
        env["AIFACTORY_VERSION_REVIEWED"] = "1"
    result = subprocess.run([executable, "--noprofile", "--norc", "-c", script],
                            capture_output=True, text=True, env=env, timeout=20)
    assert result.returncode == 0, result.stderr
    assert f"MODE:{expected}" in result.stdout


def test_supported_updaters_use_shared_checkout_without_weakening_creation():
    for name in ("ADO-update-aifactory-and-run-project.sh", "GH-update-aifactory-and-run-project.sh"):
        text = (ROOT / "bootstrap" / name).read_text(encoding="utf-8")
        if "AIFACTORY_VERSION_CONTRACT=1" not in text:
            assert 'git pull --ff-only origin' in text
            continue  # Historical v1.24 GitHub updater already retains a branch.
        assert 'aif_version_checkout "$REPO_ROOT"' in text
        assert 'checkout --detach "$AIF_SUBMODULE_REF"' not in text
    create = (ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
    assert 'checkout --detach "$AIF_SUBMODULE_REF"' in create
