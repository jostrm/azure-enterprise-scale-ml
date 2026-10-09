"""The tutorial's initial inspection is offline and never claims live access."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from .test_persona_access import BICEP, groups
from personas import inspect_manifest


SCRIPT = BICEP / "personas" / "inspect_manifest.py"
EXAMPLE = SCRIPT.with_name("manifest.example.json")


def run(path):
    return subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(path)],
                          capture_output=True, text=True, encoding="utf-8", timeout=15)


def test_tutorial_example_has_nine_offline_bindings():
    result = run(EXAMPLE)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["state"] == "offline-validated"
    assert report["cloud_checked"] is False and report["writes_performed"] is False
    assert len(report["groups"]) == 9
    assert all("object_id" not in item for item in report["groups"].values())
    assert report["groups"]["persona213"]["name"].endswith("--project001--persona213")
    assert report["missing_security_reviews"]
    assert report["lake"]["authorized_path"].endswith("/project001/environments/dev")
    assert report["lake"]["permissions"] == {"directories": "r-x", "files": "r--", "ancestors": "--x"}
    secret = report["custom_roles"]["vault-secrets"]["properties"]["permissions"][0]
    assert len(secret["dataActions"]) == 4


@pytest.mark.parametrize("changed", [{"lake": None}, {"environment": "prod"}, {"schema": "wrong"}])
def test_bad_tutorial_input_has_no_success_report(tmp_path, changed):
    value = json.loads(EXAMPLE.read_text()) | changed
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(value))
    result = run(path)
    assert result.returncode != 0 and not result.stdout
    assert "Persona manifest" in result.stderr


def test_inspector_does_not_invoke_cloud_or_seed_resolution(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Offline inspection must not contact Azure")
    monkeypatch.setattr(groups, "cli", unexpected)
    monkeypatch.setattr(groups, "resolve_seeded_groups", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    report = inspect_manifest.inspect_manifest(json.loads(EXAMPLE.read_text()))
    assert report["state"] == "offline-validated"


def test_inspector_has_no_execution_switch():
    result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(EXAMPLE), "--execute"],
                            capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode != 0 and not result.stdout
    assert "unrecognized arguments: --execute" in result.stderr
