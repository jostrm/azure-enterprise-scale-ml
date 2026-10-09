import hashlib
import ast
import json
import tarfile
from pathlib import Path

import pytest

import deploy
from aifactory_agent.config import load_settings
from aifactory_agent.costs import DEFAULT_VARIABLES_RELATIVE_PATH


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
        "costs": original.costs.model_copy(update={
            "default_variables_sha256": hashlib.sha256(template.read_bytes()).hexdigest(),
        }),
    })
    return settings, tmp_path / "bundle.tar.gz", template


def test_pinned_default_cost_template_is_in_cloud_bundle(package_inputs):
    settings, destination, _ = package_inputs
    result = deploy.package(settings, "11111111-1111-4111-8111-111111111111", destination)
    with tarfile.open(destination) as archive:
        raw = archive.extractfile("repository/" + DEFAULT_VARIABLES_RELATIVE_PATH.as_posix()).read()
        config = json.load(archive.extractfile("config.json"))
    assert hashlib.sha256(raw).hexdigest() == settings.costs.default_variables_sha256
    assert config["costs"]["default_variables_sha256"] == settings.costs.default_variables_sha256
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
    assert "workload_sources/usecase_code/50-ml-model-factory/accelerator/src" in pythonpath
    assert pythonpath.index("workload_sources/usecase_code/40-agent-factory") < pythonpath.index("/tmp/agent-app/shared")


def test_deployment_selects_exact_foundry_project_for_runtime_access():
    settings = load_settings(Path(deploy.__file__).parent / "config.example.json")
    assert deploy.resource_names(settings)["foundryProject"] == settings.azure.foundry_project


def test_runtime_identity_has_project_scoped_responses_role_not_foundry_management():
    source = (Path(deploy.__file__).parent / "infra" / "identity.bicep").read_text("utf-8")
    assert "resource project 'Microsoft.CognitiveServices/accounts/projects@" in source
    runtime = source.split("resource projectRuntime ", 1)[1].split("resource ", 1)[0]
    assert "scope: project" in runtime
    assert "'142bfaed-a13f-4c2d-bed2-6db62c4a1009'" in runtime
    assert "'53ca6127-db72-4b80-b1b0-d745d6d5456d'" not in source


def test_endpoint_deployment_selects_named_agent_and_consumption_only_role():
    settings = load_settings(Path(deploy.__file__).parent / "config.example.json")
    settings = settings.model_copy(update={"agent_invocation": "agent_endpoint"})
    assert deploy.resource_names(settings)["agentName"] == settings.agent_name
    assert deploy.resource_names(settings)["agentInvocation"] == "agent_endpoint"
    source = (Path(deploy.__file__).parent / "infra" / "identity.bicep").read_text("utf-8")
    consumer = source.split("resource agentConsumer ", 1)[1].split("resource ", 1)[0]
    assert "if (agentInvocation == 'agent_endpoint')" in consumer
    assert "scope: agent" in consumer
    assert "'eed3b665-ab3a-47b6-8f48-c9382fb1dad6'" in consumer
    project_runtime = source.split("resource projectRuntime ", 1)[1].split("resource ", 1)[0]
    assert "if (agentInvocation == 'project_reference')" in project_runtime
