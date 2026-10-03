import hashlib
import ast
import json
import tarfile
from pathlib import Path

import pytest

import deploy
from aifactory_agent.config import load_settings
from aifactory_agent.costs import DEFAULT_VARIABLES_RELATIVE_PATH, DEFAULT_VARIABLES_SHA256


@pytest.fixture
def package_inputs(tmp_path, monkeypatch):
    original = load_settings(Path(deploy.__file__).parent / "config.example.json")
    base = tmp_path / "agent"
    (base / ".build" / "wheels").mkdir(parents=True)
    (base / ".build" / "wheels" / "test-only.whl").write_bytes(b"test-only")
    (base / "aifactory_agent").mkdir()
    (base / "aifactory_agent" / "__init__.py").write_text("", encoding="utf-8")
    (base / "requirements.lock.txt").write_text("", encoding="utf-8")
    (base.parent / "agent_factory").mkdir()
    root = tmp_path / "repository"
    cli = root / "environment_setup" / "azurefactory-cli" / "src"
    cli.mkdir(parents=True)
    template = root / DEFAULT_VARIABLES_RELATIVE_PATH
    template.parent.mkdir(parents=True)
    template.write_bytes((original.knowledge.repository_root / DEFAULT_VARIABLES_RELATIVE_PATH).read_bytes())
    monkeypatch.setattr(deploy, "BASE", base)
    monkeypatch.setattr(deploy, "az", lambda *args: pytest.fail("Offline packaging must not contact Azure"))
    settings = original.model_copy(update={
        "knowledge": original.knowledge.model_copy(update={"repository_root": root, "includes": []}),
        "azure": original.azure.model_copy(update={"application_insights_name": None}),
    })
    return settings, tmp_path / "bundle.tar.gz", template


def test_pinned_default_cost_template_is_in_cloud_bundle(package_inputs):
    settings, destination, _ = package_inputs
    result = deploy.package(settings, "11111111-1111-4111-8111-111111111111", destination)
    with tarfile.open(destination) as archive:
        raw = archive.extractfile("repository/" + DEFAULT_VARIABLES_RELATIVE_PATH.as_posix()).read()
        config = json.load(archive.extractfile("config.json"))
    assert hashlib.sha256(raw).hexdigest() == DEFAULT_VARIABLES_SHA256
    assert config["costs"]["default_variables_sha256"] == DEFAULT_VARIABLES_SHA256
    assert config["costs"]["default_variables_path"] == DEFAULT_VARIABLES_RELATIVE_PATH.as_posix()
    assert config["azure"]["credential"] == "managed_identity"
    assert config["workloads"]["repository_root"] == "/tmp/agent-app/workload_sources"
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == result["sha256"]


def test_changed_default_cost_template_cannot_be_packaged(package_inputs):
    settings, destination, template = package_inputs
    template.write_text('{"dev": {}}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="trusted SHA-256"):
        deploy.package(settings, "11111111-1111-4111-8111-111111111111", destination)
    assert not destination.exists()


def test_bootstrap_uses_safe_standard_library_extraction_without_system_tar():
    script = (Path(deploy.__file__).parent / "infra" / "bootstrap.sh").read_text("utf-8")
    command = next(line for line in script.splitlines() if line.startswith("python3 -c 'import tarfile;"))
    source = command.split("'", 1)[1].rsplit("'", 1)[0]
    ast.parse(source)
    assert 'filter="data"' in source
    assert "\ntar " not in script


def test_only_approved_workload_source_entries_are_packaged(package_inputs, monkeypatch, tmp_path):
    settings, destination, _ = package_inputs
    source = tmp_path / "approved.py"
    source.write_text("APPROVED = True\n", encoding="utf-8")
    monkeypatch.setattr(deploy, "package_sources", lambda configured: [
        (source, "workload_sources/usecase_code/40-agent-factory/41-single-agent/approved.py"),
    ])
    deploy.package(settings, "11111111-1111-4111-8111-111111111111", destination)
    with tarfile.open(destination) as archive:
        content = archive.extractfile("workload_sources/usecase_code/40-agent-factory/41-single-agent/approved.py").read()
        assert content == source.read_bytes()


def test_bootstrap_prefers_approved_workload_provider_sources_to_shared_fallback():
    script = (Path(deploy.__file__).parent / "infra" / "bootstrap.sh").read_text("utf-8")
    pythonpath = next(line for line in script.splitlines() if "/tmp/agent-deps:/tmp/agent-app:" in line)
    assert "workload_sources/usecase_code/40-agent-factory" in pythonpath
    assert "workload_sources/usecase_code/50-ml-model-factory" in pythonpath
    assert pythonpath.index("workload_sources/usecase_code/40-agent-factory") < pythonpath.index("/tmp/agent-app/shared")
