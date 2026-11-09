"""Project selection and publishing receipts never turn a preview into a write."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from base.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "usecase_code/40-agent-factory"))
from agent_factory import publishing_project as project

SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
PROJECT = f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/account/projects/project"
METADATA = {
    "agentDisplayName": "Example agent", "shortDescription": "Approved short description",
    "fullDescription": "Approved full description", "developerName": "Example",
    "developerWebsiteUrl": "https://example.test", "privacyUrl": "https://example.test/privacy",
    "termsOfUseUrl": "https://example.test/terms",
}


def configuration(tmp_path, **changes):
    config = tmp_path / "variables.json"
    values = {
        "tenantId": TENANT, "enableBotService": "true", "enableAIFoundry": "true",
        "botFoundryProjectResourceId": PROJECT, "botFoundryAgentName": "example-agent",
        "botEnableM365PublicEndpoint": "false",
    }
    config.write_text(json.dumps({"dev": values | changes}), encoding="utf-8")
    return config


def fake_plan(selection, *, needs_publish=True):
    return {
        "mode": "plan", "status": "ready" if needs_publish else "unchanged",
        "target": selection.target, "preparation": {"changed": False},
        "publish_body": METADATA | {"appVersion": "1.0.0", "publishScope": selection.scope,
                                    "performBotRegistration": True, "publishAsAutopilot": False},
        "missing_fields": [], "warnings": [], "needs_publish": needs_publish,
        "active_version": {"agent_version": "@latest"},
    }


class Publisher:
    def __init__(self, selection, *, error=None, needs_publish=True):
        self.selection = selection
        self.error = error
        self.needs_publish = needs_publish
        self.applies = 0

    def plan(self, request, metadata, *, scope):
        assert request == self.selection.request
        assert scope == self.selection.scope
        return fake_plan(self.selection, needs_publish=self.needs_publish)

    def apply(self, request, metadata, *, scope, reviewed_plan):
        self.applies += 1
        receipt = json.loads(self.selection.receipt_path.read_text())
        assert receipt["state"] == "applying"
        assert reviewed_plan["publish_body"]["shortDescription"] == METADATA["shortDescription"]
        if self.error:
            raise self.error
        return {"status": "published", "published": True, "titleId": "title", "teamsAppId": "teams",
                "store_discovery_verified": False}


def test_selection_requires_no_target_parameters_and_has_no_filesystem_side_effects(tmp_path):
    config = configuration(tmp_path)
    selection = project.load_selection(config)
    assert selection.request.subscription_id == SUB
    assert selection.request.tenant_id == TENANT
    assert selection.request.enable_m365_public_endpoint is True
    assert selection.scope == "Shared"
    assert selection.profile_path.parent == tmp_path / ".foundry-publish"
    assert list(tmp_path.iterdir()) == [config]


@pytest.mark.parametrize("env", ["stage", "test", "prod"])
def test_dev_target_cannot_leak_into_later_environment(tmp_path, env):
    with pytest.raises(ValueError, match="target"):
        project.load_selection(configuration(tmp_path), environment=env)


def test_configured_subscription_must_match_explicit_project(tmp_path):
    with pytest.raises(ValueError, match="subscription"):
        project.load_selection(configuration(tmp_path, dev_sub_id="33333333-3333-4333-8333-333333333333"))


@pytest.mark.parametrize("flag", ["enableBotService", "enableAIFoundry"])
def test_disabled_configuration_is_not_overridden_to_publish(tmp_path, flag):
    with pytest.raises(ValueError):
        project.load_selection(configuration(tmp_path, **{flag: "false"}))


def test_profile_is_scoped_and_wrong_target_cannot_supply_metadata(tmp_path):
    config = configuration(tmp_path)
    selection = project.load_selection(config)
    selection.profile_path.parent.mkdir()
    selection.profile_path.write_text(json.dumps({
        "schema_version": 1, "target": selection.target | {"agent_name": "other"},
        "scope": "Tenant", "metadata": METADATA,
    }))
    with pytest.raises(ValueError, match="target"):
        project.load_selection(config)


def test_profile_scope_metadata_and_explicit_overrides(tmp_path):
    config = configuration(tmp_path)
    selection = project.load_selection(config)
    selection.profile_path.parent.mkdir()
    selection.profile_path.write_text(json.dumps({
        "schema_version": 1, "target": selection.target, "scope": "Tenant", "metadata": METADATA,
    }))
    changed = tmp_path / "metadata.json"
    changed.write_text(json.dumps({"shortDescription": "New approved description"}))
    reloaded = project.load_selection(config, scope="Shared", metadata_file=changed)
    assert reloaded.scope == "Shared"
    assert reloaded.metadata["shortDescription"] == "New approved description"
    assert reloaded.metadata["privacyUrl"] == METADATA["privacyUrl"]


def test_plan_is_read_only_even_with_missing_metadata(tmp_path):
    config = configuration(tmp_path)
    selection = project.load_selection(config)
    publisher = Publisher(selection)
    result = project.plan_publication(selection, publisher, surface="Teams")
    assert result["profile_path"] == str(selection.profile_path)
    assert result["surface"] == "Teams"
    assert list(tmp_path.iterdir()) == [config]
    assert publisher.applies == 0


def test_apply_persists_only_approved_metadata_and_scoped_receipt(tmp_path):
    config = configuration(tmp_path)
    selection = project.load_selection(config)
    publisher = Publisher(selection)
    reviewed = project.plan_publication(selection, publisher, surface="Teams")
    result = project.apply_publication(selection, publisher, reviewed, surface="Teams")
    assert publisher.applies == 1 and result["published"] is True
    profile = json.loads(selection.profile_path.read_text())
    assert profile["metadata"] == METADATA
    assert profile["target"] == selection.target
    assert "appVersion" not in profile["metadata"]
    assert json.loads(selection.receipt_path.read_text())["state"] == "completed"
    assert (selection.profile_path.parent / ".gitignore").read_text() == "*\n"


@pytest.mark.parametrize("change", ["target", "publish_body", "config_path", "active_version"])
def test_changed_review_content_prevents_files_and_apply(tmp_path, change):
    config = configuration(tmp_path)
    selection = project.load_selection(config)
    publisher = Publisher(selection)
    reviewed = project.plan_publication(selection, publisher, surface="Teams")
    reviewed[change] = {"unexpected": True}
    with pytest.raises(ValueError, match="review"):
        project.apply_publication(selection, publisher, reviewed, surface="Teams")
    assert publisher.applies == 0
    assert list(tmp_path.iterdir()) == [config]


def test_failed_apply_records_uncertainty_and_prevents_blind_repost(tmp_path):
    selection = project.load_selection(configuration(tmp_path))
    publisher = Publisher(selection, error=RuntimeError("Publication outcome uncertain."))
    plan = project.plan_publication(selection, publisher, surface="Teams")
    with pytest.raises(RuntimeError, match="uncertain"):
        project.apply_publication(selection, publisher, plan, surface="Teams")
    assert json.loads(selection.receipt_path.read_text())["state"] == "uncertain"
    second = project.plan_publication(selection, publisher, surface="Copilot")
    assert second["status"] == "blocked" and second["block_reasons"]
    with pytest.raises(ValueError, match="blocked"):
        project.apply_publication(selection, publisher, second, surface="Copilot")
    assert publisher.applies == 1


def test_explicit_recovery_is_in_preview_and_uncertain_attempt_can_be_recognized(tmp_path):
    selection = project.load_selection(configuration(tmp_path))
    selection.receipt_path.parent.mkdir()
    selection.receipt_path.write_text(json.dumps({"state": "uncertain", "target": selection.target}))
    publisher = Publisher(selection)
    reviewed = project.plan_publication(selection, publisher, surface="Teams", retry_uncertain=True)
    assert reviewed["retry_uncertain"] is True and reviewed["warnings"]
    assert reviewed["status"] == "ready"
    publisher.needs_publish = False
    result = project.plan_publication(selection, publisher, surface="Copilot")
    assert result["status"] == "unchanged"
    assert publisher.applies == 0


def test_plan_rejects_malformed_receipt_instead_of_forgetting_attempt(tmp_path):
    selection = project.load_selection(configuration(tmp_path))
    selection.receipt_path.parent.mkdir()
    selection.receipt_path.write_text("invalid")
    with pytest.raises(ValueError):
        project.plan_publication(selection, Publisher(selection), surface="Teams")


def test_custom_profile_does_not_ignore_the_users_entire_project(tmp_path):
    selection = project.load_selection(configuration(tmp_path), profile_file=tmp_path / "approved-profile.json")
    publisher = Publisher(selection)
    reviewed = project.plan_publication(selection, publisher, surface="Teams")
    project.apply_publication(selection, publisher, reviewed, surface="Teams")
    assert selection.profile_path.exists()
    assert not (tmp_path / ".gitignore").exists()


def test_existing_publisher_lock_blocks_without_overwriting_receipt(tmp_path):
    selection = project.load_selection(configuration(tmp_path))
    selection.profile_path.parent.mkdir()
    lock = selection.profile_path.with_suffix(".lock")
    lock.write_text("another process")
    publisher = Publisher(selection)
    reviewed = project.plan_publication(selection, publisher, surface="Teams")
    with pytest.raises(RuntimeError, match="Another publishing"):
        project.apply_publication(selection, publisher, reviewed, surface="Teams")
    assert publisher.applies == 0
    assert lock.read_text() == "another process"
    assert not selection.receipt_path.exists()


def test_uncertain_attempt_arriving_before_lock_acquisition_cannot_be_overwritten(tmp_path, monkeypatch):
    selection = project.load_selection(configuration(tmp_path))
    publisher = Publisher(selection)
    reviewed = project.plan_publication(selection, publisher, surface="Teams")
    competing = {"state": "uncertain", "target": selection.target, "attempt": "other-publisher"}
    original_open = os.open

    def competing_publisher_finishes(path, *args, **kwargs):
        if Path(path) == selection.profile_path.with_suffix(".lock"):
            selection.receipt_path.write_text(json.dumps(competing))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(project.os, "open", competing_publisher_finishes)
    with pytest.raises(ValueError, match="blocked"):
        project.apply_publication(selection, publisher, reviewed, surface="Teams")
    assert publisher.applies == 0
    assert json.loads(selection.receipt_path.read_text()) == competing
    assert not selection.profile_path.exists()
    assert not selection.profile_path.with_suffix(".lock").exists()


def test_duplicate_json_keys_are_rejected(tmp_path):
    config = configuration(tmp_path)
    config.write_text('{"dev": {}, "dev": {}}')
    with pytest.raises(ValueError, match="Duplicate JSON"):
        project.load_selection(config)


def test_metadata_cannot_override_publication_target_or_registration(tmp_path):
    config = configuration(tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"performBotRegistration": "false"}))
    with pytest.raises(ValueError, match="unsupported fields"):
        project.load_selection(config, metadata_file=metadata)


def test_cli_import_does_not_contact_cloud_or_execute(tmp_path):
    path = REPO_ROOT / "environment_setup/aifactory/bicep/scripts/publish-foundry-agent.py"
    spec = importlib.util.spec_from_file_location("publishing_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)


def test_shared_preparation_and_publication_suites_run_in_infrastructure_ci():
    root = REPO_ROOT / "usecase_code/40-agent-factory"
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "test_foundry_publishing", "test_m365_publishing", "-q"],
        cwd=root / "tests", env=os.environ | {"PYTHONPATH": str(root)},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
