"""Offline contracts for the opt-in project001 Dev live voice application step (on top of the chat Agent step)."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "40-aifactory-agent"))

from agent_factory import agent_live_voice as live  # noqa: E402
from agent_factory.azure import ARM, AzureError  # noqa: E402
from agent_factory.factory_chat_agent import AGENT_NAME, AI_AUDIENCE, OWNER  # noqa: E402

SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
APP = "33333333-3333-4333-8333-333333333333"
READER_A = "44444444-4444-4444-8444-444444444444"
READER_B = "55555555-5555-4555-8555-555555555555"
GROUP = "aif-esml-project001-sdc-dev-001-rg"
GROUP_ID = f"/subscriptions/{SUB}/resourceGroups/{GROUP}"
ACCOUNT_ID = f"{GROUP_ID}/providers/Microsoft.CognitiveServices/accounts/aifacct001"
PROJECT_ID = f"{ACCOUNT_ID}/projects/aifproj001"
ENV_ID = f"{GROUP_ID}/providers/Microsoft.App/managedEnvironments/aca-env-prj001"
ENDPOINT = "https://aifacct001.services.ai.azure.com/api/projects/aifproj001"
MODEL = "aifactory-agent-gpt-6-1-sol"
VALUES = {
    "enableFactoryChatAgent": "true", "enableAIFactoryAgentLiveVoice": "true",
    "enableContainerApps": "true", "enableAIFoundry": "true", "enableAISearch": "true",
    "deleteAllServicesForProject": "false", "deleteAllForProject": "false",
    "dev_test_prod_sub_id": SUB, "tenantId": TENANT, "dev_test_prod": "dev", "project_number_000": "001",
    "admin_location": "swedencentral", "admin_aifactoryPrefixRG": "aif-", "projectPrefix": "esml-",
    "admin_locationSuffix": "sdc", "admin_aifactorySuffixRG": "-001", "projectSuffix": "-rg",
    "modelGPTXName": MODEL, "aifactoryAgentEntraAppId": APP, "aifactoryAgentReaderObjectIds": f"{READER_A}, {READER_B}",
    "aifactoryAgentContainerAppsEnvironment": "", "aifactoryAgentVoiceName": "", "aifactoryAgentVoiceLanguages": "",
}


def values(**changes):
    return {**VALUES, **changes}


class FakeArm:
    """Read-only Azure fake: records every call; refuses any write."""

    def __init__(self, deployments=None, environments=None, agent="owned"):
        self.calls, self.agent = [], agent
        self.resources = {
            PROJECT_ID.lower(): {"id": PROJECT_ID, "name": "aifacct001/aifproj001", "identity": {"principalId": READER_A},
                                 "properties": {"endpoints": {"AI Foundry API": ENDPOINT}}},
            ENV_ID.lower(): {"id": ENV_ID, "properties": {"vnetConfiguration": {"internal": True}, "defaultDomain": "internal.example"}},
        }
        self.lists = {
            f"{GROUP_ID}/resources": [
                {"id": ACCOUNT_ID, "name": "aifacct001", "type": "Microsoft.CognitiveServices/accounts", "kind": "AIServices", "location": "swedencentral"},
                {"id": f"{GROUP_ID}/providers/Microsoft.Search/searchServices/srch001", "name": "srch001", "type": "Microsoft.Search/searchServices"},
                {"id": f"{GROUP_ID}/providers/Microsoft.Storage/storageAccounts/saprj0011001", "name": "saprj0011001", "type": "Microsoft.Storage/storageAccounts"},
                {"id": f"{GROUP_ID}/providers/Microsoft.Storage/storageAccounts/saprj0012001", "name": "saprj0012001", "type": "Microsoft.Storage/storageAccounts"},
                *(environments if environments is not None else [{"id": ENV_ID, "name": "aca-env-prj001", "type": "Microsoft.App/managedEnvironments"}]),
                {"id": f"{GROUP_ID}/providers/Microsoft.Insights/components/appi001", "name": "appi001", "type": "Microsoft.Insights/components"},
            ],
            f"{ACCOUNT_ID}/projects": [{"id": PROJECT_ID, "name": "aifacct001/aifproj001"}],
            f"{ACCOUNT_ID}/deployments": deployments if deployments is not None else [
                {"name": MODEL, "sku": {"name": "DataZoneStandard", "capacity": 100},
                 "properties": {"provisioningState": "Succeeded", "model": {"format": "OpenAI", "name": "gpt-6.1-sol", "version": "2026-09-29"}}},
                {"name": "other-chat", "properties": {"provisioningState": "Succeeded", "model": {"format": "OpenAI", "name": "gpt-x", "version": "1"}}},
                {"name": "text-embedding-3-large", "properties": {"provisioningState": "Succeeded", "model": {"format": "OpenAI", "name": "text-embedding-3-large"}}},
            ],
        }

    def arm(self, method, resource_id, body=None, api_version="x"):
        self.calls.append((method, resource_id))
        if method != "GET":
            raise AssertionError(f"The live voice step must not write through ARM ({method} {resource_id})")
        if resource_id.lower() in self.resources:
            return copy.deepcopy(self.resources[resource_id.lower()])
        raise AzureError(404, method, resource_id, "NotFound")

    def request(self, method, url, body=None, *, audience=ARM, headers=None):
        self.calls.append((method, url))
        if method != "GET" or not url.startswith(f"{ENDPOINT}/agents/{AGENT_NAME}?"):
            raise AssertionError(f"unexpected request {method} {url}")
        assert audience == AI_AUDIENCE
        if self.agent == "missing":
            raise AzureError(404, method, url, "NotFound")
        if self.agent == "forbidden":
            raise AzureError(403, method, url, "Forbidden")
        if self.agent == "no-version":
            return {"name": AGENT_NAME}
        owner = OWNER if self.agent == "owned" else "someone-else"
        return {"name": AGENT_NAME, "versions": {"latest": {"version": "3", "metadata": {"aifactory.managed_by": owner}}}}

    def pages(self, url, *, audience=ARM, field="value"):
        self.calls.append(("LIST", url))
        path = url[len(ARM):].split("?", 1)[0]
        for key, items in self.lists.items():
            if path.endswith(key):
                return copy.deepcopy(items)
        return []


class FakeRunner:
    """Records commands; returns canned JSON like the real operator commands print."""

    def __init__(self, fail_on=None):
        self.calls, self.fail_on, self.configs = [], fail_on, []

    def __call__(self, args, *, cwd, env=None):
        self.calls.append({"args": list(args), "cwd": Path(cwd)})
        text = " ".join(map(str, args))
        if "--config" in args:
            self.configs.append(json.loads(Path(args[args.index("--config") + 1]).read_text("utf-8")))
        if self.fail_on and self.fail_on in text:
            raise live.CommandError(f"{self.fail_on} failed (exit 1)")
        if "ingest" in args:
            return json.dumps({"status": "ready", "indexed_document_count": 12})
        if args[-1] == "--apply":
            return json.dumps({"deployment_state": "Succeeded", "outputs": {"fqdn": {"value": "agent.internal.example"}},
                               "plan": {"image": "x"}, "bundle": {"sha256": "s"}})
        return ""

    def names(self):
        return [self.step_name(call["args"]) for call in self.calls]

    @staticmethod
    def step_name(args):
        text = " ".join(map(str, args))
        for name in ("venv", "pip install", "pip download", "ingest", "deploy.py"):
            if name in text:
                return name
        return text


def request(**changes):
    return live.LiveVoiceRequest.from_values(values(**changes))


# ---- decisions -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("chat", ["true", "false"])
def test_voice_off_does_nothing_here_because_the_chat_agent_has_its_own_step(chat):
    decision = live.decide(request(enableFactoryChatAgent=chat, enableAIFactoryAgentLiveVoice="false"))
    assert decision.act is False and "enableFactoryChatAgent" in decision.reason


def test_both_flags_true_deploys_the_voice_application():
    decision = live.decide(request())
    assert decision.act is True and decision.voice is True


def test_live_voice_without_chat_is_a_loud_configuration_error_not_a_silent_skip():
    with pytest.raises(ValueError, match="enableAIFactoryAgentLiveVoice requires enableFactoryChatAgent"):
        live.decide(request(enableFactoryChatAgent="false"))


def test_only_project001_dev_acts_other_projects_fail_and_other_environments_skip():
    with pytest.raises(ValueError, match="only for project001"):
        live.decide(request(project_number_000="002"))
    for environment in ("test", "prod"):
        decision = live.decide(request(dev_test_prod=environment))
        assert decision.act is False and "Dev" in decision.reason


@pytest.mark.parametrize("flag", ["deleteAllServicesForProject", "deleteAllForProject"])
def test_delete_runs_conflict_with_enabled_options(flag):
    with pytest.raises(ValueError, match="conflict"):
        live.decide(request(**{flag: "true"}))


@pytest.mark.parametrize("missing", ["enableContainerApps", "enableAIFoundry", "enableAISearch"])
def test_dependencies_are_validated_not_ignored(missing):
    with pytest.raises(ValueError, match=missing):
        live.decide(request(**{missing: "false"}))


@pytest.mark.parametrize("changes,message", [
    ({"aifactoryAgentEntraAppId": ""}, "aifactoryAgentEntraAppId"),
    ({"aifactoryAgentEntraAppId": "not-a-guid"}, "aifactoryAgentEntraAppId"),
    ({"aifactoryAgentEntraAppId": "$(aifactoryAgentEntraAppId)"}, "aifactoryAgentEntraAppId"),
    ({"aifactoryAgentReaderObjectIds": ""}, "aifactoryAgentReaderObjectIds"),
    ({"aifactoryAgentReaderObjectIds": "nope"}, "aifactoryAgentReaderObjectIds"),
    ({"aifactoryAgentReaderObjectIds": ",".join(f"{n:08d}-0000-4000-8000-{n:012d}" for n in range(1, 25))}, "at most 20"),
    ({"modelGPTXName": ""}, "modelGPTXName"),
    ({"modelGPTXName": "bad name!"}, "modelGPTXName"),
    ({"aifactoryAgentVoiceName": "bad;voice"}, "aifactoryAgentVoiceName"),
    ({"aifactoryAgentVoiceLanguages": "not a locale"}, "aifactoryAgentVoiceLanguages"),
    ({"dev_test_prod_sub_id": "x"}, "dev_test_prod_sub_id"),
    ({"tenantId": ""}, "tenantId"),
    ({"admin_location": ""}, "admin_location"),
])
def test_invalid_inputs_fail_with_the_exact_variable_name(changes, message):
    with pytest.raises(ValueError, match=message):
        live.decide(request(**changes))


def test_flags_accept_only_canonical_booleans_and_treat_unset_ado_macros_as_false():
    with pytest.raises(ValueError, match="enableAIFactoryAgentLiveVoice must be true or false"):
        live.LiveVoiceRequest.from_values(values(enableAIFactoryAgentLiveVoice="yes"))
    off = live.LiveVoiceRequest.from_values(values(enableFactoryChatAgent="$(enableFactoryChatAgent)", enableAIFactoryAgentLiveVoice=""))
    assert off.enable_chat is False and off.enable_live_voice is False


def test_resource_group_follows_the_factory_naming_convention_unless_given():
    assert request().resource_group == GROUP
    assert request(projectResourceGroup="custom-rg").resource_group == "custom-rg"


# ---- discovery -------------------------------------------------------------------------------------------------

def test_discovery_resolves_the_projects_foundry_search_storage_insights_agent_and_internal_environment_read_only():
    arm = FakeArm()
    target = live.discover(arm, request())
    assert target.account_name == "aifacct001" and target.project_name == "aifproj001"
    assert target.project_endpoint == ENDPOINT and target.agent_version == "3"
    assert target.model == {"name": MODEL, "model": "gpt-6.1-sol", "version": "2026-09-29", "sku": "DataZoneStandard", "capacity": 100}
    assert target.embedding == "text-embedding-3-large" and target.search_name == "srch001"
    assert target.storage_name == "saprj0012001" and target.insights_name == "appi001"
    assert target.environment_name == "aca-env-prj001"
    assert all(call[0] in {"GET", "LIST"} for call in arm.calls)


def test_the_model_deployment_comes_from_modelGPTXName_and_a_missing_one_is_a_clear_prerequisite_error():
    assert live.discover(FakeArm(), request(modelGPTXName="other-chat")).model["name"] == "other-chat"
    with pytest.raises(ValueError, match=f"{MODEL}.*modelGPTXName.*Deploy-Model"):
        live.discover(FakeArm(deployments=[]), request())
    with pytest.raises(ValueError, match="missing-model"):
        live.discover(FakeArm(), request(modelGPTXName="missing-model"))


def test_a_deployment_that_is_not_succeeded_does_not_count():
    deployments = [{"name": MODEL, "properties": {"provisioningState": "Creating",
                    "model": {"format": "OpenAI", "name": "gpt", "version": "1"}}}]
    with pytest.raises(ValueError, match="succeeded"):
        live.discover(FakeArm(deployments=deployments), request())


def test_the_hosting_environment_must_be_internal_and_unambiguous():
    second = {"id": ENV_ID + "-2", "name": "aca-env-other", "type": "Microsoft.App/managedEnvironments"}
    first = {"id": ENV_ID, "name": "aca-env-prj001", "type": "Microsoft.App/managedEnvironments"}
    with pytest.raises(ValueError, match="aifactoryAgentContainerAppsEnvironment"):
        live.discover(FakeArm(environments=[first, second]), request())
    arm = FakeArm(environments=[first, second])
    assert live.discover(arm, request(aifactoryAgentContainerAppsEnvironment="aca-env-prj001")).environment_name == "aca-env-prj001"
    public = FakeArm()
    public.resources[ENV_ID.lower()]["properties"]["vnetConfiguration"] = {"internal": False}
    with pytest.raises(ValueError, match="internal"):
        live.discover(public, request())


def test_the_foundry_agent_from_the_chat_step_must_exist_and_be_owned_by_the_factory():
    with pytest.raises(ValueError, match="does not exist yet.*enableFactoryChatAgent"):
        live.discover(FakeArm(agent="missing"), request())
    with pytest.raises(ValueError, match="not owned by the Enterprise Scale AI Factory"):
        live.discover(FakeArm(agent="foreign"), request())
    with pytest.raises(ValueError, match="no valid latest version"):
        live.discover(FakeArm(agent="no-version"), request())
    with pytest.raises(AzureError) as denied:
        live.discover(FakeArm(agent="forbidden"), request())
    assert denied.value.status == 403


# ---- generated application configuration ---------------------------------------------------------------------

def render(**changes):
    req = request(**changes)
    return live.render_config(req, live.discover(FakeArm(), req), repository_root=Path("/work/checkout"))


def test_the_generated_configuration_is_valid_for_the_applications_own_schema_with_voice_on():
    pytest.importorskip("pydantic")
    from aifactory_agent.config import Settings
    settings = Settings.model_validate(render())
    assert settings.voice.enabled is True and settings.azure.credential == "cli" and settings.factory.writes_enabled is False
    assert list(settings.scopes) == ["project001-dev"] and settings.scopes["project001-dev"].environment == "dev"
    assert settings.agent_name == AGENT_NAME


def test_grants_are_read_only_and_exactly_the_listed_users_and_no_secret_is_present():
    config = render()
    assert config["auth"]["client_id"] == APP and config["auth"]["audience"] == "api://" + APP
    assert config["auth"]["grants"] == [
        {"object_id": READER_A, "scopes": ["project001-dev"], "permissions": ["knowledge.read", "factory.read"]},
        {"object_id": READER_B, "scopes": ["project001-dev"], "permissions": ["knowledge.read", "factory.read"]}]
    scrubbed = {**config, "knowledge": {key: item for key, item in config["knowledge"].items() if key != "excludes"}}
    text = json.dumps(scrubbed).lower()
    assert not any(word in text for word in ("secret", "password", "connection_string", "config.write", "factory.delete", "cost.read"))
    assert config["actions"] == {"enabled_skills": []}


def test_the_voice_block_follows_the_optional_overrides():
    assert render()["voice"] == {"enabled": True, "voice_name": "en-US-Ava:DragonHDLatestNeural", "input_languages": ["en-US"]}
    swedish = render(aifactoryAgentVoiceName="sv-SE-SofieNeural", aifactoryAgentVoiceLanguages="sv-SE, en-US")["voice"]
    assert swedish["voice_name"] == "sv-SE-SofieNeural" and swedish["input_languages"] == ["sv-SE", "en-US"]


# ---- orchestration ---------------------------------------------------------------------------------------------

def integration(tmp_path, runner=None, arm=None):
    runner = runner or FakeRunner()
    return live.LiveVoiceIntegration(arm or FakeArm(), runner, work_dir=tmp_path, repository_root=Path("/work/checkout")), runner


def test_skipped_runs_touch_nothing(tmp_path):
    engine, runner = integration(tmp_path)
    report = engine.run(request(enableAIFactoryAgentLiveVoice="false"), apply=True)
    assert report["mode"] == "skipped" and report["mutations"] is False and runner.calls == []
    assert engine.session.calls == []


def test_plan_reads_azure_but_runs_no_command_and_lists_prerequisites(tmp_path):
    engine, runner = integration(tmp_path)
    report = engine.run(request(), apply=False)
    assert report["mode"] == "plan" and report["mutations"] is False and runner.calls == []
    assert [step["resource"] for step in report["actions"]] == [
        "isolated python environment", "linux wheels for the bundle", "knowledge index", "container app"]
    assert all(step["action"] == "would run" for step in report["actions"])
    joined = " ".join(report["prerequisites"])
    assert "Entra" in joined and "enableFactoryChatAgent" in joined and "Foundry User" in joined
    assert report["outputs"]["voice"] is True and report["outputs"]["agent"] == {"name": AGENT_NAME, "version": "3"}
    assert (tmp_path / "config.json").exists()


def test_apply_runs_the_documented_operator_sequence_in_order_with_the_generated_config(tmp_path):
    engine, runner = integration(tmp_path)
    report = engine.run(request(), apply=True)
    assert runner.names() == ["venv", "pip install", "pip download", "ingest", "deploy.py"]
    agent_directory = ROOT / "40-aifactory-agent"
    assert all(call["cwd"] == agent_directory for call in runner.calls[1:] if "venv" not in " ".join(map(str, call["args"][:3])))
    config_paths = {call["args"][call["args"].index("--config") + 1] for call in runner.calls if "--config" in call["args"]}
    assert config_paths == {str(tmp_path / "config.json")} and not str(tmp_path).startswith(str(ROOT))
    last = runner.calls[-1]["args"]
    assert last[-1] == "--apply" and "--environment" in last and last[last.index("--environment") + 1] == "aca-env-prj001"
    assert report["mode"] == "apply" and report["mutations"] is True
    assert report["outputs"]["agent"] == {"name": AGENT_NAME, "version": "3"}
    assert report["outputs"]["knowledge"] == {"status": "ready", "indexed_document_count": 12}
    assert report["outputs"]["app"] == {"fqdn": "agent.internal.example", "deployment_state": "Succeeded"}
    assert report["outputs"]["voice"] is True and runner.configs[0]["voice"]["enabled"] is True
    assert "secret" not in json.dumps(report).lower()


def test_the_step_never_creates_the_foundry_agent(tmp_path):
    engine, runner = integration(tmp_path)
    engine.run(request(), apply=True)
    assert not any("deploy-agent" in " ".join(map(str, call["args"])) for call in runner.calls)


def test_a_failed_step_stops_the_sequence_and_does_not_leak_command_output(tmp_path):
    engine, runner = integration(tmp_path, runner=FakeRunner(fail_on="ingest"))
    with pytest.raises(live.CommandError, match="knowledge index failed"):
        engine.run(request(), apply=True)
    assert "deploy.py" not in runner.names() and runner.names()[-1] == "ingest"


@pytest.mark.parametrize("arm", [FakeArm(deployments=[]), FakeArm(agent="missing"), FakeArm(agent="foreign")])
def test_missing_prerequisites_fail_before_any_command_runs(tmp_path, arm):
    engine, runner = integration(tmp_path, arm=arm)
    with pytest.raises(ValueError):
        engine.run(request(), apply=True)
    assert runner.calls == []


def test_nothing_is_ever_deleted_and_azure_is_only_read_by_the_engine(tmp_path):
    engine, runner = integration(tmp_path)
    engine.run(request(), apply=True)
    commands = [" ".join(map(str, call["args"])).replace(str(tmp_path), "<work>").lower() for call in runner.calls]
    assert commands and not any("delete" in command for command in commands)
    assert all(call[0] in {"GET", "LIST"} for call in engine.session.calls)


# ---- launcher (what the ADO task and the GitHub Actions step run) -----------------------------------------------

def launcher():
    spec = importlib.util.spec_from_file_location("agent_live_voice_launcher", ROOT / "47-aifactory-agent-live-voice" / "deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(command="apply", apply=True):
    return type("Args", (), {"command": command, "apply": apply})()


def no_azure(*_):
    raise AssertionError("Azure must not be contacted")


def test_the_launcher_reads_exactly_the_pipeline_variables_the_engine_needs():
    module = launcher()
    assert set(module.INPUTS) == set(VALUES) | {"projectResourceGroup"} and len(set(module.INPUTS)) == len(module.INPUTS)
    assert module.REPOSITORY_ROOT == ROOT.parents[1]


def test_disabled_validate_and_invalid_runs_never_reach_azure():
    module = launcher()
    off = values(enableAIFactoryAgentLiveVoice="false")
    assert module.run(arguments(), off, no_azure)["mode"] == "skipped"
    assert module.run(arguments("validate", False), VALUES, no_azure) == {
        "mode": "validated", "reason": "Validated project001 Dev AI Factory Agent live voice request.", "voice": True,
        "mutations": False}
    with pytest.raises(ValueError, match="requires --apply"):
        module.run(arguments("apply", False), VALUES, no_azure)
    with pytest.raises(ValueError, match="requires enableFactoryChatAgent"):
        module.run(arguments("plan", False), values(enableFactoryChatAgent="false"), no_azure)
    with pytest.raises(ValueError, match="aifactoryAgentEntraAppId"):
        module.run(arguments("plan", False), values(aifactoryAgentEntraAppId="$(aifactoryAgentEntraAppId)"), no_azure)


def test_plan_reads_azure_only_and_apply_runs_the_engine_in_a_work_directory_outside_the_checkout(tmp_path):
    module, arm, runner = launcher(), FakeArm(), FakeRunner()
    environ = values(RUNNER_TEMP=str(tmp_path))
    plan = module.run(arguments("plan", False), environ, lambda subscription, tenant: arm, runner)
    assert plan["mode"] == "plan" and plan["mutations"] is False and runner.calls == []
    applied = module.run(arguments(), environ, lambda subscription, tenant: arm, runner)
    assert applied["mode"] == "apply" and runner.names()[-1] == "deploy.py" and applied["outputs"]["voice"] is True
    assert (tmp_path / "aifactory-agent-live-voice" / "config.json").is_file()
    assert module.work_directory({"AGENT_TEMPDIRECTORY": str(tmp_path)}) == tmp_path / "aifactory-agent-live-voice"
    assert not str(module.work_directory({})).startswith(str(ROOT.parents[1]))


def test_the_command_line_reports_configuration_and_command_errors_in_one_line(monkeypatch, capsys):
    module = launcher()
    monkeypatch.setattr(sys, "argv", ["deploy.py", "validate"])
    for name in module.INPUTS:
        monkeypatch.delenv(name, raising=False)
    for name, value in values(enableFactoryChatAgent="false").items():
        monkeypatch.setenv(name, value)
    assert module.main() == 1
    error = capsys.readouterr().err
    assert "requires enableFactoryChatAgent" in error and "Traceback" not in error
    monkeypatch.setattr(module, "run", lambda args: (_ for _ in ()).throw(live.CommandError("ingest failed (exit 1)")))
    assert module.main() == 1 and "ingest failed (exit 1)" in capsys.readouterr().err
