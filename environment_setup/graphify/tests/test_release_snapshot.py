import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "usecase_code" / "40-agent-factory" / "40-aifactory-agent"))
from aifactory_agent.dual_graph import DualGraphStore, publish_snapshot

MODULE = Path(__file__).resolve().parents[1] / "release_snapshot.py"
spec = importlib.util.spec_from_file_location("aifactory_graph_release_snapshot", MODULE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

TAG = "release_125"
REVISION = "a" * 40


def make_snapshot(root: Path, *, revision: str = REVISION, dirty: bool = False) -> str:
    graph = {"directed": True, "multigraph": True, "graph": {"schema_version": 1},
             "nodes": [{"id": "bootstrap/a.py::function:run", "label": "run", "kind": "function",
                        "source_file": "bootstrap/a.py", "evidence": "static", "resolution": "resolved"}],
             "links": []}
    metadata = {"source": {"revision": revision, "dirty": dirty}, "tools": {}, "settings": {},
                "exclusions": [], "coverage": {}, "inputs": []}
    return publish_snapshot(root, graph, {"Index.md": "# Architecture\n"}, metadata)["snapshot_id"]


def exported(root: Path) -> dict:
    return DualGraphStore(root).export_snapshot()


class FakeCommands:
    """Records git/gh/test commands in order and answers them from a small state."""

    def __init__(self, *, dirty=False, tests_pass=True, tag_commit=None, remote_tag=False,
                 release_exists=False, assets=(), pushed=True):
        self.calls, self.dirty, self.tests_pass = [], dirty, tests_pass
        self.tag_commit, self.remote_tag, self.release_exists = tag_commit, remote_tag, release_exists
        self.assets, self.pushed = list(assets), pushed

    def __call__(self, args, cwd=None):
        args = [str(item) for item in args]
        self.calls.append(args)
        out, code = "", 0
        if args[:2] == ["git", "status"]:
            out = " M changed.py\n" if self.dirty else ""
        elif args[:3] == ["git", "rev-parse", "HEAD"]:
            out = REVISION + "\n"
        elif args[:2] == ["git", "rev-parse"]:
            code, out = (0, self.tag_commit + "\n") if self.tag_commit else (1, "")
        elif args[:3] == ["git", "branch", "-r"]:
            out = "  origin/release/v1.25\n" if self.pushed else ""
        elif args[:2] == ["git", "ls-remote"]:
            out = f"{REVISION}\trefs/tags/{TAG}\n" if self.remote_tag else ""
        elif args[:3] == ["gh", "release", "view"]:
            code = 0 if self.release_exists else 1
            out = json.dumps({"assets": [{"name": name} for name in self.assets]})
        elif "run_ci.py" in " ".join(args):
            code = 0 if self.tests_pass else 1
            results = Path(args[args.index("--results-dir") + 1])
            results.mkdir(parents=True, exist_ok=True)
            (results / "unit-summary.json").write_text(json.dumps(
                {"phases": ["unit"], "failed": [] if self.tests_pass else ["unit"],
                 "tiers": {"selected": "all", "source": "option", "skipped": []}}), encoding="utf-8")
        return subprocess.CompletedProcess(args, code, out, "")

    def find(self, *prefix):
        return [call for call in self.calls if call[:len(prefix)] == list(prefix)]


def publish(tmp_path, commands, *, apply=False, generated=None):
    repository = tmp_path / "repo"
    (repository / "meta" / "graphify").mkdir(parents=True, exist_ok=True)
    calls = []

    def generate(root, output):
        calls.append(("generate", root, output))
        return {"snapshot_id": make_snapshot(output)}

    result = release.publish(
        repository, TAG, apply=apply, run=commands, generate=generated or generate,
        test_python="python-for-tests", fresh=lambda store: True)
    return result, calls


# --- tag and checksum rules -------------------------------------------------------------------

@pytest.mark.parametrize("tag", ["release_125", "release_1250"])
def test_release_tags_follow_the_existing_release_nnn_convention(tag):
    assert release.check_tag(tag) == tag


@pytest.mark.parametrize("tag", ["release/v1.25", "v1.25", "release_12", "release_125-rc1", "", "release_125\n"])
def test_other_tag_names_are_rejected(tag):
    with pytest.raises(release.ReleaseError):
        release.check_tag(tag)


def test_asset_names_are_derived_from_the_tag():
    assert release.asset_names(TAG) == ("aifactory-dual-graph-release_125.zip",
                                        "aifactory-dual-graph-release_125.zip.sha256")


# --- publish gate -------------------------------------------------------------------------------

def test_a_dirty_checkout_is_refused_before_tests_or_generation(tmp_path):
    commands = FakeCommands(dirty=True)
    with pytest.raises(release.ReleaseError, match="uncommitted"):
        publish(tmp_path, commands)
    assert not [call for call in commands.calls if "run_ci.py" in " ".join(call)]


def test_an_unpushed_commit_is_refused(tmp_path):
    with pytest.raises(release.ReleaseError, match="pushed"):
        publish(tmp_path, FakeCommands(pushed=False))


def test_an_existing_tag_on_another_commit_is_refused(tmp_path):
    with pytest.raises(release.ReleaseError, match="another commit"):
        publish(tmp_path, FakeCommands(tag_commit="b" * 40))


def test_failing_tier_one_to_five_tests_stop_before_generation_and_upload(tmp_path):
    commands = FakeCommands(tests_pass=False)
    with pytest.raises(release.ReleaseError, match="tiers 1-5"):
        _, calls = publish(tmp_path, commands, apply=True)
    assert not commands.find("git", "tag")
    assert not commands.find("git", "push")
    assert not [call for call in commands.calls if call[:1] == ["gh"] and call[1:2] != ["release"]]
    assert not commands.find("gh", "release", "create")
    assert not commands.find("gh", "release", "upload")


def test_every_tier_runs_with_the_requested_interpreter(tmp_path):
    commands = FakeCommands()
    publish(tmp_path, commands)
    test_run = next(call for call in commands.calls if "run_ci.py" in " ".join(call))
    assert test_run[0] == "python-for-tests"
    assert test_run[test_run.index("--phase") + 1] == "unit"
    assert test_run[test_run.index("--tiers") + 1] == "all"


def test_without_apply_nothing_is_tagged_pushed_or_uploaded(tmp_path):
    commands = FakeCommands()
    result, calls = publish(tmp_path, commands)
    assert [call[0] for call in calls] == ["generate"]
    assert not commands.find("git", "tag") and not commands.find("git", "push")
    assert not commands.find("gh", "release", "create") and not commands.find("gh", "release", "upload")
    assert result["applied"] is False
    assert Path(result["asset"]).is_file() and Path(result["checksum"]).is_file()
    assert any("gh release upload" in step for step in result["next_steps"])


def test_apply_tags_pushes_creates_the_release_and_uploads_after_green_tests(tmp_path):
    commands = FakeCommands()
    result, _ = publish(tmp_path, commands, apply=True)
    order = [" ".join(call[:3]) for call in commands.calls]
    tests = next(index for index, call in enumerate(commands.calls) if "run_ci.py" in " ".join(call))
    tag = order.index("git tag -a")
    assert tests < tag < order.index("git push origin") < order.index("gh release create")
    assert order.index("gh release create") < order.index("gh release upload")
    upload = commands.find("gh", "release", "upload")[0]
    assert "--clobber" not in upload
    assert result["applied"] is True


def test_apply_refuses_to_replace_an_uploaded_snapshot(tmp_path):
    asset, checksum = release.asset_names(TAG)
    commands = FakeCommands(tag_commit=REVISION, remote_tag=True, release_exists=True, assets=[asset, checksum])
    with pytest.raises(release.ReleaseError, match="already has"):
        publish(tmp_path, commands, apply=True)
    assert not commands.find("gh", "release", "upload")


def test_a_snapshot_from_uncommitted_source_is_never_packaged(tmp_path):
    def dirty_generate(root, output):
        return {"snapshot_id": make_snapshot(output, dirty=True)}

    with pytest.raises(release.ReleaseError, match="uncommitted"):
        publish(tmp_path, FakeCommands(), generated=dirty_generate)


def test_a_snapshot_from_another_revision_is_never_packaged(tmp_path):
    def other_generate(root, output):
        return {"snapshot_id": make_snapshot(output, revision="c" * 40)}

    with pytest.raises(release.ReleaseError, match="revision"):
        publish(tmp_path, FakeCommands(), generated=other_generate)


# --- package and install ----------------------------------------------------------------------

def test_package_is_deterministic_and_checksummed(tmp_path):
    make_snapshot(tmp_path / "graph")
    first = release.package(exported(tmp_path / "graph"), TAG, REVISION, tmp_path / "a")
    second = release.package(exported(tmp_path / "graph"), TAG, REVISION, tmp_path / "b")
    assert Path(first["asset"]).read_bytes() == Path(second["asset"]).read_bytes()
    digest = hashlib.sha256(Path(first["asset"]).read_bytes()).hexdigest()
    assert Path(first["checksum"]).read_text(encoding="utf-8") == f"{digest}  {Path(first['asset']).name}\n"
    with zipfile.ZipFile(first["asset"]) as archive:
        names = archive.namelist()
        info = json.loads(archive.read("release.json"))
    snapshot_id = first["snapshot_id"]
    assert "release.json" in names
    assert f"snapshots/{snapshot_id}/manifest.json" in names
    assert f"snapshots/{snapshot_id}/graph.json" in names
    assert info == {"tag": TAG, "snapshot_id": snapshot_id, "source_revision": REVISION,
                    "tests": {"tiers": "all", "result": "passed"}}


def test_install_round_trip_gives_a_pinned_queryable_snapshot(tmp_path):
    snapshot_id = make_snapshot(tmp_path / "graph")
    packaged = release.package(exported(tmp_path / "graph"), TAG, REVISION, tmp_path / "dist")
    root = tmp_path / "meta" / "graphify"
    result = release.install(Path(packaged["asset"]), Path(packaged["checksum"]), root)
    assert result["snapshot_id"] == snapshot_id
    target = root / "snapshots" / snapshot_id
    assert Path(result["snapshot_root"]) == target
    status = DualGraphStore(target, expected_snapshot_id=snapshot_id).query("status")
    assert status["results"][0]["nodes"] == 1
    assert not (root / "current.json").exists(), "Fetching must not change the local generation pointer."
    again = release.install(Path(packaged["asset"]), Path(packaged["checksum"]), root)
    assert again["snapshot_id"] == snapshot_id
    assert sorted(path.name for path in (root / "snapshots").iterdir()) == [snapshot_id]


def test_install_rejects_a_checksum_mismatch_and_leaves_nothing(tmp_path):
    make_snapshot(tmp_path / "graph")
    packaged = release.package(exported(tmp_path / "graph"), TAG, REVISION, tmp_path / "dist")
    asset = Path(packaged["asset"])
    asset.write_bytes(asset.read_bytes() + b"tampered")
    root = tmp_path / "meta" / "graphify"
    with pytest.raises(release.ReleaseError, match="checksum"):
        release.install(asset, Path(packaged["checksum"]), root)
    assert not (root / "snapshots").exists() or not any((root / "snapshots").iterdir())


def rewrite(asset: Path, checksum: Path, change):
    with zipfile.ZipFile(asset) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    change(members)
    with zipfile.ZipFile(asset, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    checksum.write_text(f"{hashlib.sha256(asset.read_bytes()).hexdigest()}  {asset.name}\n", encoding="utf-8")


def test_install_rejects_a_snapshot_that_fails_its_own_integrity_manifest(tmp_path):
    snapshot_id = make_snapshot(tmp_path / "graph")
    packaged = release.package(exported(tmp_path / "graph"), TAG, REVISION, tmp_path / "dist")
    asset, checksum = Path(packaged["asset"]), Path(packaged["checksum"])
    rewrite(asset, checksum, lambda members: members.update(
        {f"snapshots/{snapshot_id}/graph.json": members[f"snapshots/{snapshot_id}/graph.json"] + b" "}))
    root = tmp_path / "meta" / "graphify"
    with pytest.raises(release.ReleaseError, match="integrity"):
        release.install(asset, checksum, root)
    assert not (root / "snapshots" / snapshot_id).exists()
    assert not [path for path in (root / "snapshots").iterdir()]


@pytest.mark.parametrize("name", ["../evil.json", "snapshots/../../evil.json", "/abs.json", "other/file.json"])
def test_install_rejects_unexpected_or_escaping_members(tmp_path, name):
    make_snapshot(tmp_path / "graph")
    packaged = release.package(exported(tmp_path / "graph"), TAG, REVISION, tmp_path / "dist")
    asset, checksum = Path(packaged["asset"]), Path(packaged["checksum"])
    rewrite(asset, checksum, lambda members: members.update({name: b"{}"}))
    with pytest.raises(release.ReleaseError):
        release.install(asset, checksum, tmp_path / "meta" / "graphify")
    assert not (tmp_path / "evil.json").exists()


def test_fetch_downloads_the_named_assets_with_the_github_cli(tmp_path):
    make_snapshot(tmp_path / "graph")
    packaged = release.package(exported(tmp_path / "graph"), TAG, REVISION, tmp_path / "dist")
    calls = []

    def run(args, cwd=None):
        args = [str(item) for item in args]
        calls.append(args)
        target = Path(args[args.index("--dir") + 1])
        for path in (packaged["asset"], packaged["checksum"]):
            (target / Path(path).name).write_bytes(Path(path).read_bytes())
        return subprocess.CompletedProcess(args, 0, "", "")

    result = release.fetch(TAG, tmp_path / "meta" / "graphify", run=run)
    assert calls[0][:4] == ["gh", "release", "download", TAG]
    asset, checksum = release.asset_names(TAG)
    assert ["--pattern", asset] == calls[0][calls[0].index("--pattern"):calls[0].index("--pattern") + 2]
    assert checksum in calls[0]
    assert result["snapshot_id"] == packaged["snapshot_id"]


def test_meta_graphify_ignores_release_assets_but_keeps_its_readme():
    for path, ignored in (("meta/graphify/release-assets/aifactory-dual-graph-release_125.zip", True),
                          ("meta/graphify/readme.md", False)):
        result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=REPO, check=False)
        assert result.returncode == (0 if ignored else 1), path
