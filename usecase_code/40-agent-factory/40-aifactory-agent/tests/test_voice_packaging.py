"""Packaging and infrastructure contract for live voice: offline-installable dependency, least-privilege roles, plan."""

import json
import re
from pathlib import Path

import pytest

import deploy
from aifactory_agent.config import Settings

ROOT = Path(__file__).parents[1]
COGNITIVE_SERVICES_USER = "a97b65f3-24c7-4388-baec-2e87135dc908"
AZURE_AI_USER = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
OPENAI_USER = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"


def settings(**voice):
    config = json.loads((ROOT / "config.example.json").read_text("utf-8"))
    config["voice"] = {"enabled": False, **voice}
    return Settings.model_validate(config)


def test_the_websocket_library_is_a_pinned_offline_installable_dependency():
    requirements = (ROOT / "requirements.txt").read_text("utf-8")
    lock = (ROOT / "requirements.lock.txt").read_text("utf-8")
    assert re.search(r"^websockets>=14,<18\s*$", requirements, re.M)
    pins = re.findall(r"^websockets==(\d+)\.(\d+(?:\.\d+)?)\s*$", lock, re.M)
    assert len(pins) == 1 and 14 <= int(pins[0][0]) < 18
    names = [line.split("==")[0].lower() for line in lock.splitlines() if "==" in line]
    assert names == sorted(names), "the lock stays alphabetical so reviews and diffs stay small"


def test_the_hardened_runtime_identity_template_has_no_voice_role_and_the_voice_roles_are_opt_in_and_separate():
    identity = (ROOT / "infra" / "identity.bicep").read_text("utf-8")
    assert "enableLiveVoice" not in identity and AZURE_AI_USER not in identity and COGNITIVE_SERVICES_USER not in identity
    voice = (ROOT / "infra" / "voice-roles.bicep").read_text("utf-8")
    assignments = re.findall(r"resource (\w+) 'Microsoft.Authorization/roleAssignments@[^']+' = \{(.*?)\n\}", voice, re.S)
    assert [name for name, _ in assignments] == ["voiceCognitiveServicesUser", "voiceFoundryUser"]
    for (_, body), role in zip(assignments, (COGNITIVE_SERVICES_USER, AZURE_AI_USER)):
        assert role in body and "scope: foundry" in body and "principalType: 'ServicePrincipal'" in body
    assert "if (" not in voice and "Owner" not in voice and "Contributor" not in voice
    assert "param identityName string" in voice and "param foundryAccount string" in voice


def test_the_deployment_plan_discloses_the_extra_foundry_roles_only_when_voice_is_enabled():
    off = deploy.identity_permissions(settings())
    on = deploy.identity_permissions(settings(enabled=True))
    assert on[:len(off)] == off and len(on) == len(off) + 1
    assert "Voice Live" in on[-1] and "Cognitive Services User" in on[-1] and "Foundry User" in on[-1]
    assert not any("Voice Live" in item for item in off)


def test_voice_role_arguments_target_the_runtime_identity_and_the_foundry_account_only():
    names = {"searchName": "s", "storageName": "t", "storageContainer": "c", "foundryAccount": "f"}
    assert deploy.voice_role_arguments("mi-test", names) == ["identityName=mi-test", "foundryAccount=f"]


class StopDeployment(Exception):
    pass


def run_apply(monkeypatch, enabled):
    config = json.loads((ROOT / "config.example.json").read_text("utf-8"))
    config["voice"] = {"enabled": enabled}
    calls = []

    def fake_az(*args):
        calls.append(args)
        if args[:2] == ("resource", "show"):
            return {"properties": {"vnetConfiguration": {"internal": True}}}
        if args[:2] == ("resource", "list"):
            return []
        return {"properties": {"outputs": {"clientId": {"value": "client"}}}}

    def stop(*_):
        raise StopDeployment

    monkeypatch.setattr(deploy, "az", fake_az)
    monkeypatch.setattr(deploy, "package", stop)
    monkeypatch.setattr(deploy, "load_settings", lambda _: Settings.model_validate(config))
    monkeypatch.setattr("sys.argv", ["deploy.py", "--config", "unused.json", "--environment", "aca-env", "--apply"])
    with pytest.raises(StopDeployment):
        deploy.main()
    return [call[call.index("--name") + 1] for call in calls if call[:2] == ("deployment", "group")]


def test_apply_deploys_the_voice_roles_after_the_identity_and_only_when_voice_is_enabled(monkeypatch):
    assert run_apply(monkeypatch, False) == ["aifactory-agent-identity"]
    assert run_apply(monkeypatch, True) == ["aifactory-agent-identity", "aifactory-agent-voice-roles"]


def test_the_packaged_config_carries_the_voice_block_but_never_a_credential():
    cloud = settings(enabled=True).model_dump(mode="json")
    assert cloud["voice"]["enabled"] is True
    assert "key" not in json.dumps(cloud["voice"]).lower() and "secret" not in json.dumps(cloud["voice"]).lower()
