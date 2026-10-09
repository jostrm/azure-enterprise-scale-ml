import importlib.util
import json
import sys
from pathlib import Path

import pytest


DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_snapshot_rejects_unsafe_paths_before_writing(tmp_path):
    release = load("release")
    for name in ("../secret", "/absolute", "C:\\secret", "a/../../b"):
        with pytest.raises(ValueError):
            release.safe_relative(name)


def test_release_ref_requires_full_immutable_commit():
    release = load("release")
    for value in ("main", "HEAD", "3e9102ee", "a" * 39, "a" * 41):
        with pytest.raises(ValueError):
            release.validate_ref(value)
    assert release.validate_ref("a" * 40) == "a" * 40


def test_manifest_hash_and_verification_bind_every_release_file(tmp_path):
    release = load("release")
    (tmp_path / "code.py").write_text("pass\n", encoding="utf-8")
    manifest = release.write_manifest(tmp_path, {"purpose": "test"})
    assert release.verify_release(tmp_path)["release_hash"] == manifest["release_hash"]
    (tmp_path / "code.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        release.verify_release(tmp_path)


def test_manifest_rejects_extra_files_and_modified_metadata(tmp_path):
    release = load("release")
    (tmp_path / "code.py").write_text("pass\n", encoding="utf-8")
    release.write_manifest(tmp_path, {"purpose": "test"})
    (tmp_path / "secret.txt").write_text("not part of release", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        release.verify_release(tmp_path)
    (tmp_path / "secret.txt").unlink()
    manifest_path = tmp_path / "release.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["metadata"]["purpose"] = "different"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash"):
        release.verify_release(tmp_path)


def test_pilot_configuration_rejects_writes_and_unapproved_tools():
    launcher = load("launch")
    config = {
        "factory": {"writes_enabled": False},
        "actions": {"enabled_skills": []},
        "workloads": {"enabled_skills": []},
        "auth": {"grants": [{"permissions": ["factory.read"]}]},
    }
    auth = {"identities": [{"allowed_tools": ["factory_health", "factory_capabilities", "factory_skills"]}]}
    launcher.validate_pilot(config, auth)
    config["factory"]["writes_enabled"] = True
    with pytest.raises(ValueError):
        launcher.validate_pilot(config, auth)
    config["factory"]["writes_enabled"] = False
    auth["identities"][0]["allowed_tools"] = ["factory_execute_operation"]
    with pytest.raises(ValueError):
        launcher.validate_pilot(config, auth)


def test_pilot_configuration_rejects_privileged_delegated_grant():
    launcher = load("launch")
    with pytest.raises(ValueError):
        launcher.validate_pilot({
            "factory": {"writes_enabled": False}, "actions": {"enabled_skills": []},
            "auth": {"grants": [{"permissions": ["factory.delete"]}]},
        }, {"identities": [{"allowed_tools": ["factory_health"]}]})
