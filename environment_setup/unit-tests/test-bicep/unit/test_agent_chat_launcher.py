"""ADO/GHA-azurefactory.sh add-aifactory-agent-chat --to-project NNN: the bash route for the AI Factory Agent chat.

The launcher only forwards; bootstrap/lib/agent_chat_entry.py resolves the project's own variables file, maps it to the
pipeline variable names and runs the same two launchers as the project pipeline (46 chat Agent, then 47 application with
live voice). Plan is the default; --apply is explicit.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
BASH = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
if not BASH.is_file():
    BASH = shutil.which("bash")
ENTRY = ROOT / "bootstrap/lib/agent_chat_entry.py"
SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
APP = "33333333-3333-4333-8333-333333333333"
READER = "44444444-4444-4444-8444-444444444444"


def entry():
    spec = importlib.util.spec_from_file_location("agent_chat_entry_contract", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def project_values(number="012", **changes):
    return {
        "project_number_000": number, "dev_sub_id": SUB, "tenantId": TENANT, "admin_location": "swedencentral",
        "admin_aifactoryPrefixRG": "spider-", "projectPrefix": "esml-", "admin_locationSuffix": "sdc",
        "admin_aifactorySuffixRG": "-001", "projectSuffix": "-rg", "modelGPTXName": "gpt-5.4-mini",
        "enableContainerApps": "true", "enableAIFoundry": "true", "enableAISearch": "true",
        "enableFactoryChatAgent": "false", "enableAIFactoryAgentLiveVoice": "false",
        "aifactoryAgentEntraAppId": APP, "aifactoryAgentReaderObjectIds": READER,
        "aifactoryAgentContainerAppsEnvironment": "", "aifactoryAgentVoiceName": "", "aifactoryAgentVoiceLanguages": "",
        "aifactoryAgentConfigFile": "", "deleteAllForProject": "false", "deleteAllServicesForProject": "false",
        **changes,
    }


def write(path: Path, values: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"dev": values, "stage_prod": {}}), encoding="utf-8")
    return path


def registered(tmp_path, number="012", **changes):
    root = tmp_path / "consumer"
    (root / "azurefactory").mkdir(parents=True)
    (root / "azurefactory/register.json").write_text('{"schema_version":2}', encoding="utf-8")
    write(root / f"azurefactory/factories/spider/scalesets/001/projects/project{number}/variables.json",
          project_values(number, **changes))
    return root


class Recorder:
    def __init__(self, name, order=None):
        self.name, self.calls, self.order = name, [], order

    def __call__(self, args, environ):
        if self.order is not None:
            self.order.append(self.name)
        self.calls.append({"command": args.command, "apply": args.apply, "environ": dict(environ)})
        return {"mode": "apply" if args.apply else args.command, "step": self.name, "mutations": args.apply}


def run(module, arguments, chat=None, voice=None, provider="ado"):
    chat, voice = chat or Recorder("chat"), voice or Recorder("voice")
    result = module.main([provider, *arguments], chat_runner=chat, voice_runner=voice)
    return result, chat, voice


# ---- bash forwarding -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("provider", ["ADO", "GHA"])
@pytest.mark.parametrize("action", ["add-aifactory-agent-chat", "--add-aifactory-agent-chat", "-addAIFactoryAgentChat"])
@pytest.mark.parametrize("adapter_in_submodule", [False, True])
def test_launchers_forward_the_agent_chat_action_with_provider_and_exact_arguments(
        tmp_path, provider, action, adapter_in_submodule):
    root = tmp_path / "registered consumer"
    library = root / "lib"
    library.mkdir(parents=True)
    shutil.copyfile(ROOT / "bootstrap/lib/layout_router.sh", library / "layout_router.sh")
    shutil.copyfile(ROOT / f"bootstrap/{provider}-azurefactory.sh", root / f"{provider}-azurefactory.sh")
    adapter_root = root / "azure-enterprise-scale-ml/bootstrap/lib" if adapter_in_submodule else library
    adapter_root.mkdir(parents=True, exist_ok=True)
    (adapter_root / "agent_chat_entry.py").write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(3)\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AIF_", "AIFACTORY_")) and key not in ("BASH_ENV", "ENV", "SHELLOPTS")}
    env["AIFACTORY_PYTHON"] = sys.executable
    arguments = ["--to-project", "012", "--environment", "dev", "--apply"]
    result = subprocess.run(
        [str(BASH), "--noprofile", "--norc", str(root / f"{provider}-azurefactory.sh"), action, *arguments],
        cwd=root, env=env, input="", capture_output=True, text=True, timeout=30)
    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout) == [provider.lower(), *arguments]


@pytest.mark.parametrize("provider", ["ADO", "GHA"])
def test_help_lists_the_agent_chat_action(provider):
    result = subprocess.run([str(BASH), "--noprofile", "--norc", str(ROOT / f"bootstrap/{provider}-azurefactory.sh"), "--help"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and "add-aifactory-agent-chat --to-project <NNN>" in result.stderr


def test_the_entry_ships_in_the_dual_layout_bundle():
    router = (ROOT / "bootstrap/lib/layout_router.sh").read_text(encoding="utf-8")
    assert "  agent_chat_entry.py\n" in router


# ---- entry: arguments ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("arguments, message", [
    ([], "--to-project is required"),
    (["--to-project"], "--to-project is required"),
    (["--to-project", "12a"], "3-digit project number such as 001"),
    (["--to-project", "000"], "3-digit project number such as 001"),
    (["--to-project", "project012"], "3-digit project number such as 001"),
    (["--to-project", "012", "--environment", "prod"], "Dev only"),
    (["--to-project", "012", "--unknown"], "Unsupported argument: --unknown"),
])
def test_invalid_arguments_fail_before_anything_runs(tmp_path, arguments, message, capsys):
    root = registered(tmp_path)
    result, chat, voice = run(entry(), [*arguments, "--consumer-root", str(root)])
    assert result == 2 and message in capsys.readouterr().err
    assert chat.calls == [] and voice.calls == []


def test_short_project_numbers_are_normalized_to_three_digits(tmp_path):
    root = registered(tmp_path)
    result, _, voice = run(entry(), ["--to-project", "12", "--consumer-root", str(root)])
    assert result == 0 and voice.calls[0]["environ"]["project_number_000"] == "012"


def test_the_documented_short_form_to_project_option_is_accepted(tmp_path):
    # "-addAIFactoryAgentChat -toProject 001" is the form the operators were given; it must mean --to-project.
    root = registered(tmp_path)
    result, _, voice = run(entry(), ["-toProject", "012", "--consumer-root", str(root)])
    assert result == 0 and voice.calls[0]["environ"]["project_number_000"] == "012"


# ---- entry: configuration resolution ---------------------------------------------------------------------------

def test_a_registered_root_uses_the_projects_own_variables_file(tmp_path, capsys):
    root = registered(tmp_path)
    write(root / "aifactory/variables.json", project_values("001"))
    result, _, _ = run(entry(), ["--to-project", "012", "--consumer-root", str(root)])
    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["configuration"] == "azurefactory/factories/spider/scalesets/001/projects/project012/variables.json"
    assert report["mode"] == "plan" and report["mutations"] is False


def test_a_legacy_root_uses_aifactory_variables_json_only_for_its_own_project(tmp_path, capsys):
    root = tmp_path / "legacy"
    write(root / "aifactory/variables.json", project_values("001"))
    result, _, voice = run(entry(), ["--to-project", "001", "--consumer-root", str(root)])
    assert result == 0 and voice.calls[0]["environ"]["project_number_000"] == "001"
    capsys.readouterr()
    result, _, voice = run(entry(), ["--to-project", "012", "--consumer-root", str(root)])
    assert result == 2 and "--config" in capsys.readouterr().err and voice.calls == []


def test_an_explicit_config_must_belong_to_the_selected_project(tmp_path, capsys):
    root = tmp_path / "legacy"
    config = write(root / "other/project.json", project_values("003"))
    result, _, voice = run(entry(), ["--to-project", "012", "--consumer-root", str(root), "--config", str(config)])
    assert result == 2 and "project_number_000 is 003" in capsys.readouterr().err and voice.calls == []


def test_two_projects_with_the_same_number_are_ambiguous(tmp_path, capsys):
    root = registered(tmp_path)
    write(root / "azurefactory/factories/other/scalesets/002/projects/project012/variables.json", project_values())
    result, _, voice = run(entry(), ["--to-project", "012", "--consumer-root", str(root)])
    assert result == 2 and "--config" in capsys.readouterr().err and voice.calls == []


# ---- entry: what runs ------------------------------------------------------------------------------------------

def test_plan_maps_the_variables_file_to_pipeline_variables_and_turns_the_agent_options_on(tmp_path):
    root = registered(tmp_path)
    result, chat, voice = run(entry(), ["--to-project", "012", "--consumer-root", str(root)])
    assert result == 0
    for recorder in (chat, voice):
        call = recorder.calls[0]
        assert call["command"] == "plan" and call["apply"] is False
        environ = call["environ"]
        assert environ["dev_test_prod"] == "dev" and environ["dev_test_prod_sub_id"] == SUB
        assert environ["enableFactoryChatAgent"] == "true" and environ["enableAIFactoryAgentLiveVoice"] == "true"
        assert environ["BUILD_SOURCESDIRECTORY"] == str(root)
        assert environ["deleteAllForProject"] == "false" and environ["deleteAllServicesForProject"] == "false"


def test_apply_runs_the_chat_agent_before_the_application(tmp_path):
    root = registered(tmp_path)
    order = []
    chat, voice = Recorder("chat", order), Recorder("voice", order)
    result, _, _ = run(entry(), ["--to-project", "012", "--consumer-root", str(root), "--apply"],
                       chat=chat, voice=voice, provider="gha")
    assert result == 0 and order == ["chat", "voice"]
    assert chat.calls[0]["command"] == "apply" and chat.calls[0]["apply"] is True
    assert voice.calls[0]["command"] == "apply" and voice.calls[0]["apply"] is True


def test_without_voice_skips_the_voice_application_and_a_failed_chat_step_stops(tmp_path, capsys):
    root = registered(tmp_path)
    result, chat, voice = run(entry(), ["--to-project", "012", "--consumer-root", str(root), "--without-voice"])
    assert result == 0 and voice.calls == [] and chat.calls[0]["environ"]["enableAIFactoryAgentLiveVoice"] == "false"

    def failing(args, environ):
        raise ValueError("Factory Chat Agent prerequisites missing")
    result, _, voice = run(entry(), ["--to-project", "012", "--consumer-root", str(root)], chat=failing)
    assert result == 1 and voice.calls == [] and "prerequisites missing" in capsys.readouterr().err


def test_the_agent_configuration_option_overrides_the_variables_file(tmp_path):
    root = registered(tmp_path, aifactoryAgentConfigFile="aifactory/agent/old.json")
    result, _, voice = run(entry(), ["--to-project", "012", "--consumer-root", str(root),
                                     "--agent-config", "aifactory/agent/project012-dev.json"])
    assert result == 0 and voice.calls[0]["environ"]["aifactoryAgentConfigFile"] == "aifactory/agent/project012-dev.json"


def test_missing_agent_settings_are_named_with_the_file_to_edit(tmp_path, capsys):
    root = registered(tmp_path, aifactoryAgentEntraAppId="", aifactoryAgentReaderObjectIds="")
    result, chat, voice = run(entry(), ["--to-project", "012", "--consumer-root", str(root)])
    error = capsys.readouterr().err
    assert result == 2 and chat.calls == [] and voice.calls == []
    assert "aifactoryAgentEntraAppId" in error and "aifactoryAgentReaderObjectIds" in error and "project012/variables.json" in error


def test_the_report_never_echoes_identifiers_or_configuration_values(tmp_path, capsys):
    root = registered(tmp_path)
    run(entry(), ["--to-project", "012", "--consumer-root", str(root)])
    out = capsys.readouterr().out
    assert SUB not in out and TENANT not in out and READER not in out



def test_skip_knowledge_is_passed_to_the_voice_step_only(tmp_path):
    root = registered(tmp_path)
    module = entry()
    seen = []

    def voice(args, environ):
        seen.append(getattr(args, "skip_knowledge", None))
        return {"mode": "plan"}

    assert module.main(["ado", "--to-project", "012", "--consumer-root", str(root), "--skip-knowledge"],
                       chat_runner=Recorder("chat"), voice_runner=voice) == 0
    assert seen == [True]
    seen.clear()
    assert module.main(["ado", "--to-project", "012", "--consumer-root", str(root)],
                       chat_runner=Recorder("chat"), voice_runner=voice) == 0
    assert seen == [False]
