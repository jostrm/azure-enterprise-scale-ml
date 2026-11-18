import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import deploy
from test_skill_packaging import package_inputs


ROOT = Path(__file__).parents[1]


def settings(enabled):
    return SimpleNamespace(teams_meetings=SimpleNamespace(enabled=enabled))


def test_meeting_scale_is_explicit_and_normal_chat_defaults_are_preserved():
    assert deploy.application_scale_parameters(settings(False)) == {
        "minReplicas": 1, "maxReplicas": 2, "attendedMeetingsEnabled": False,
    }
    assert deploy.application_scale_parameters(settings(True)) == {
        "minReplicas": 1, "maxReplicas": 1, "attendedMeetingsEnabled": True,
    }
    assert deploy.meeting_runtime_limitation(settings(False)) is None
    note = deploy.meeting_runtime_limitation(settings(True))
    assert note["asgi_workers"] == note["replicas"] == 1
    assert "per-process" in note["reason"]


def test_meeting_infrastructure_pins_process_local_state_and_exposes_plan():
    bicep = (ROOT / "infra" / "application.bicep").read_text("utf-8")
    assert "param attendedMeetingsEnabled bool = false" in bicep
    assert "minReplicas: attendedMeetingsEnabled ? 1 : minReplicas" in bicep
    assert "maxReplicas: attendedMeetingsEnabled ? 1 : maxReplicas" in bicep
    assert "name: 'WEB_CONCURRENCY', value: '1'" in bicep
    source = (ROOT / "deploy.py").read_text("utf-8")
    assert "**application_scale_parameters(settings)" in source
    assert '"attended_meeting_pilot": meeting_runtime_limitation(settings)' in source


def test_acs_infrastructure_is_separate_keyless_and_never_grants_implicitly():
    bicep = (ROOT / "infra" / "teams-meeting-acs.bicep").read_text("utf-8")
    assert "targetScope = 'resourceGroup'" in bicep
    assert "disableLocalAuth: true" in bicep
    assert "param grantTokenBrokerContributor bool = false" in bicep
    assert "= if (grantTokenBrokerContributor)" in bicep
    assert "scope: communication" in bicep
    assert "principalType: 'ServicePrincipal'" in bicep
    assert "listKeys" not in bicep and "clientSecret" not in bicep
    assert "Microsoft.App/" not in bicep and "Microsoft.Network/" not in bicep


def test_meeting_is_opt_in_and_ships_sdk_without_runtime_cdn():
    config = json.loads((ROOT / "config.example.json").read_text("utf-8"))
    assert config["teams_meetings"]["enabled"] is False
    html = (ROOT / "aifactory_agent" / "static" / "index.html").read_text("utf-8")
    assert 'src="/static/teams-meeting.js"' in html
    assert 'href="/static/teams-meeting.css"' in html
    entry = (ROOT / "aifactory_agent" / "static" / "teams-meeting-frontend" / "sdk-entry.js").read_text("utf-8")
    assert "Features" in entry
    requirements = (ROOT / "requirements.txt").read_text("utf-8")
    lock = (ROOT / "requirements.lock.txt").read_text("utf-8")
    assert "azure-communication-identity>=1.5,<2" in requirements
    assert "azure-communication-identity==1.5.0" in lock


def test_runtime_bundle_keeps_sdk_and_notices_but_excludes_installed_build_dependencies(package_inputs):
    configured, destination, _ = package_inputs
    static = deploy.BASE / "aifactory_agent" / "static"
    for relative in (
        "vendor/teams-meeting-sdk.min.js",
        "teams-meeting-frontend/THIRD-PARTY-NOTICES.txt",
        "teams-meeting-frontend/node_modules/esbuild/bin/esbuild",
    ):
        path = static / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test fixture", encoding="utf-8")
    deploy.package(configured, "11111111-1111-4111-8111-111111111111", destination)
    with tarfile.open(destination) as archive:
        names = archive.getnames()
    assert "aifactory_agent/static/vendor/teams-meeting-sdk.min.js" in names
    assert "aifactory_agent/static/teams-meeting-frontend/THIRD-PARTY-NOTICES.txt" in names
    assert not any("node_modules" in name.split("/") for name in names)
