import json
import copy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from test_release_scaffold import DEPLOY, load

sys.path.insert(0, str(DEPLOY))


def test_rollout_defaults_to_preview_and_requires_exact_approval():
    module = load("rollout")
    plan = module.seal({"schema_version": 1, "target": module.TARGET, "release_hash": "a" * 64})
    with pytest.raises(ValueError, match="approval"):
        module.require_approval(plan, None)
    with pytest.raises(ValueError, match="approval"):
        module.require_approval(plan, "b" * 64)
    module.require_approval(plan, plan["plan_hash"])
    assert module.parser().parse_args(["--phase", "plan"]).phase == "plan"


def test_native_command_resolves_azure_cli_batch_launcher_without_a_shell(monkeypatch):
    module = load("rollout")
    calls = []
    monkeypatch.setattr(module.shutil, "which", lambda command: r"C:\AzureCLI\wbin\az.CMD")
    monkeypatch.setattr(module.Path, "is_file", lambda path: True)
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: (
        calls.append((command, kwargs)) or SimpleNamespace(returncode=0, stdout="ok")
    ))
    assert module.run(["az", "version"]) == "ok"
    assert calls[0][0] == [r"C:\AzureCLI\python.exe", "-I", "-m", "azure.cli", "version"]
    assert calls[0][1].get("shell", False) is False


def test_missing_or_unknown_batch_executable_fails_closed(monkeypatch):
    module = load("rollout")
    monkeypatch.setattr(module.shutil, "which", lambda command: None)
    with pytest.raises(RuntimeError, match="executable"):
        module.run(["az", "version"])
    monkeypatch.setattr(module.shutil, "which", lambda command: r"C:\tools\other.cmd")
    with pytest.raises(RuntimeError, match="batch"):
        module.run(["other", "data&command"])


def test_native_executable_receives_literal_argument_array(monkeypatch):
    module = load("rollout")
    calls = []
    monkeypatch.setattr(module.shutil, "which", lambda command: r"C:\Docker\docker.exe")
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: (
        calls.append(command) or SimpleNamespace(returncode=0, stdout="id")
    ))
    assert module.run(["docker", "inspect", "image"]) == "id"
    assert calls == [[r"C:\Docker\docker.exe", "inspect", "image"]]


def test_rollout_rejects_modified_or_cross_scope_plan():
    module = load("rollout")
    plan = module.seal({"target": module.TARGET, "release_hash": "a" * 64})
    plan["release_hash"] = "b" * 64
    with pytest.raises(ValueError, match="hash"):
        module.require_approval(plan, plan["plan_hash"])
    other = module.seal({"target": {**module.TARGET, "appName": "aif-mcp-project001-dev"}})
    with pytest.raises(ValueError, match="target"):
        module.require_approval(other, other["plan_hash"])


@pytest.mark.parametrize("image", [
    "other.azurecr.io/aifactory-mcp@sha256:" + "a" * 64,
    "acrcommonbltscsdc001dev.azurecr.io/aifactory-mcp:latest",
    "acrcommonbltscsdc001dev.azurecr.io/aifactory-mcp@sha256:short",
])
def test_rollout_accepts_only_exact_registry_digest(image):
    module = load("rollout")
    with pytest.raises(ValueError):
        module.validate_image(image, "aifactory-mcp")


def test_rollout_uses_immutable_registry_image():
    module = load("rollout")
    image = "acrcommonbltscsdc001dev.azurecr.io/aifactory-mcp@sha256:" + "a" * 64
    assert module.validate_image(image, "aifactory-mcp") == image


def test_pilot_config_removes_old_grants_and_action_targets():
    module = load("rollout")
    base = {"factory": {"writes_enabled": True}, "auth": {"grants": [{"permissions": ["factory.delete"]}]},
            "actions": {"enabled_skills": ["delete-aifactory"]}, "costs": {"secret": "unused"},
            "workloads": {"enabled_skills": ["create"]}, "scopes": {"project001-dev": {"project": "001"}}}
    config = module.pilot_config(base)
    assert config["factory"]["writes_enabled"] is False
    assert config["actions"] == {"enabled_skills": []}
    assert config["costs"] == config["workloads"] == {}
    assert all(grant["permissions"] == ["factory.read"] for grant in config["auth"]["grants"])
    assert len(config["auth"]["grants"]) == 2
    assert base["factory"]["writes_enabled"] is True


def test_journal_claim_prevents_blind_retry(tmp_path):
    module = load("rollout")
    journal = module.Journal(tmp_path / "journal.json", "a" * 64)
    journal.claim("identity")
    assert journal.data["stages"]["identity"] == "started"
    loaded = module.Journal(tmp_path / "journal.json", "a" * 64)
    with pytest.raises(ValueError, match="inspect"):
        loaded.claim("identity")
    loaded.complete("identity", {"application_id": "example"})
    with pytest.raises(ValueError, match="inspect"):
        loaded.claim("identity")
    with pytest.raises(ValueError, match="different"):
        module.Journal(tmp_path / "journal.json", "b" * 64)


def test_parameter_builder_never_emits_api_key(tmp_path):
    module = load("rollout")
    inputs = module.parameters("{}", "{}", "https://example.com/mcp", application=True)
    assert inputs["deployApplication"]["value"] is True
    assert "apiKey" not in inputs
    assert inputs["apiKeySecretName"]["value"] == "aifactory-mcp-api-key-dev"


class FakeCloud:
    def __init__(self, module):
        self.module = module
        self.calls = []
        self.queries = {
            "/me?": {"id": module.TARGET["operator"]},
            "/projects/": {"identity": {"principalId": module.TARGET["projectPrincipal"],
                                       "tenantId": module.TARGET["tenant"]}},
            "/managedEnvironments/": {"properties": {
                "vnetConfiguration": {"internal": True},
                "defaultDomain": "agreeableground-46dbeb46.swedencentral.azurecontainerapps.io",
            }},
            "/vaults/": {"properties": {"enableRbacAuthorization": True, "publicNetworkAccess": "Disabled"}},
            "/registries/": {"properties": {"adminUserEnabled": False, "publicNetworkAccess": "Disabled"}},
        }

    def request(self, method, url, body=None, *, headers=None):
        self.calls.append((method, url, body, headers))
        for match, response in self.queries.items():
            if match in url:
                return copy.deepcopy(response)
        return {}


def test_preflight_only_reads_and_checks_private_dependencies():
    module = load("rollout")
    cloud = FakeCloud(module)
    assert module.preflight(cloud).endswith("/mcp")
    assert all(call[0] == "GET" for call in cloud.calls)
    cloud.queries["/vaults/"]["properties"]["publicNetworkAccess"] = "Enabled"
    with pytest.raises(ValueError, match="Vault"):
        module.preflight(cloud)


def test_preflight_refuses_other_operator_and_unowned_app():
    module = load("rollout")
    cloud = FakeCloud(module)
    cloud.queries["/me?"]["id"] = "other"
    with pytest.raises(ValueError, match="operator"):
        module.preflight(cloud)
    cloud.queries["/me?"]["id"] = module.TARGET["operator"]
    cloud.queries["/containerApps/"] = {"tags": {"aifactory.managed_by": "another"}}
    with pytest.raises(ValueError, match="ownership"):
        module.preflight(cloud)


def test_identity_collision_does_not_create_or_replace():
    module = load("rollout")
    cloud = FakeCloud(module)
    cloud.queries["/applications?"] = {"value": [{"id": "already-exists"}]}
    with pytest.raises(ValueError, match="already exists"):
        module.execute_stage("identity", {}, None, cloud, "https://example.com/mcp")
    assert len(cloud.calls) == 1 and cloud.calls[0][0] == "GET"


def test_secret_stage_uses_injected_secret_port():
    module = load("rollout")

    class Cloud:
        def create_api_secret(self):
            return {"secret_id": "https://vault.example/secrets/one/version"}

    assert module.execute_stage("secret", {}, None, Cloud(), "unused") == {
        "secret_id": "https://vault.example/secrets/one/version",
    }


def test_rollback_default_is_non_mutating_and_never_deletes(tmp_path):
    module = load("rollout")
    journal = module.Journal(tmp_path / "journal.json", "a" * 64)
    preview = module.rollback({"plan_hash": "a" * 64}, journal, None, None)
    assert preview["delete_resources"] is False
    assert not journal.path.exists()
    with pytest.raises(ValueError, match="approval"):
        module.rollback({"plan_hash": "a" * 64}, journal, None, "wrong")


def test_emergency_rollback_preview_does_not_require_release_or_current_source(tmp_path, monkeypatch, capsys):
    module = load("rollout")
    plan = module.seal({
        "target": module.TARGET, "release_hash": "a" * 64,
        "release": str(tmp_path / "removed-release"), "source_hashes": {"changed.py": "old"},
    })
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["rollout.py", "--phase", "rollback", "--plan", str(path)])
    monkeypatch.setattr(module, "AzureCloud", lambda: pytest.fail("Preview must not authenticate"))
    module.main()
    output = json.loads(capsys.readouterr().out)
    assert output["deployment_plan_hash"] == plan["plan_hash"]
    assert output["delete_resources"] is False

def test_published_images_must_belong_to_approved_local_image(monkeypatch):
    module = load("rollout")
    images = {
        "mcp": "acrcommonbltscsdc001dev.azurecr.io/aifactory-mcp@sha256:" + "a" * 64,
        "api": "acrcommonbltscsdc001dev.azurecr.io/aifactory-api@sha256:" + "b" * 64,
    }
    plan = {"local_image_ids": {"mcp": "mcp-id", "api": "api-id"}}
    monkeypatch.setattr(module, "run", lambda cmd: json.dumps([images["mcp"]] if "mcp-id" in cmd else [images["api"]]))
    assert module.published_images(plan, images) == images
    monkeypatch.setattr(module, "run", lambda cmd: "[]")
    with pytest.raises(ValueError, match="bound"):
        module.published_images(plan, images)


def test_bicep_preserves_approved_two_image_and_existing_vault_design():
    root = DEPLOY.parent / "infra"
    main = (root / "main.bicep").read_text()
    app = (root / "modules" / "application.bicep").read_text()
    grants = (root / "modules" / "role-assignments.bicep").read_text()
    assert "param mcpImage string" in main and "param apiImage string" in main
    assert "image: mcpImage" in app and "image: apiImage" in app
    assert "scope: apiKeySecret" in grants
    assert "4633458b-17de-408a-b874-0445c86b69e6" in grants
    assert "b86a8fe4-44ce-4948-aee5-eccb2c155cd7" not in grants
    assert "existing =" in grants
    assert "cpu: json('0.5')" in app
