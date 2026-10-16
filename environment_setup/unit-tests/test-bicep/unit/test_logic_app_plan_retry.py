"""Offline same-plan retry contracts; no Azure allocation or deployment."""

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from unittest.mock import Mock

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "environment_setup/aifactory/bicep/scripts/deploy-integration-with-retry.py"
SUB = "11111111-1111-1111-1111-111111111111"
RG = f"/subscriptions/{SUB}/resourceGroups/project-rg"
PLAN = RG + "/providers/Microsoft.Web/serverfarms/appfarm-logicapp01"
MESSAGE = ("No available instances to satisfy this request. "
           "App Service is attempting to increase capacity. Please retry your request later.")
TEMPLATE = {"parameters": {name: {"type": kind} for name, kind in {
    "skuLogicAppsDev": "string", "env": "string", "privateValue": "secureString",
    "tagsProject": "object", "enableLogicApps": "bool", "workerCount": "int",
}.items()}}


@pytest.fixture
def retry():
    spec = importlib.util.spec_from_file_location("logic_plan_retry", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capacity_error():
    service = {"Code": "Conflict", "Message": MESSAGE, "Target": None,
               "Details": [{"Message": MESSAGE}, {"Code": "Conflict"}, {"ErrorEntity": {
                   "ExtendedCode": "03029", "Code": "Conflict", "Message": MESSAGE,
                   "MessageTemplate": MESSAGE, "Parameters": [],
               }}], "Innererror": None}
    return {"status": "Failed", "error": {
        "code": "DeploymentFailed", "target": f"/subscriptions/{SUB}/providers/Microsoft.Resources/deployments/integration",
        "details": [{"code": "ResourceDeploymentFailure", "target": RG + "/providers/Microsoft.Resources/deployments/logic-plan",
                     "details": [{"code": "DeploymentFailed", "details": [
                         {"code": "Conflict", "target": PLAN, "message": json.dumps(service)}]}]}],
    }}


def test_exact_nested_appservice_capacity_response_is_retryable(retry):
    assert retry.is_plan_capacity_error("ERROR: " + json.dumps(capacity_error()), SUB)


def test_persisted_cli_error_with_nullable_code_preserves_capacity_evidence(retry):
    payload = {"code": "DeploymentFailed", "target": RG + "/providers/Microsoft.Resources/deployments/logic-plan",
               "details": [{"code": None, "target": PLAN, "message": MESSAGE,
                            "details": None, "additionalInfo": None}], "additionalInfo": None}
    assert retry.is_plan_capacity_error(json.dumps(payload), SUB)


@pytest.mark.parametrize("second", ["other-rg", "unknown-conflict", "wrong-extended-code"])
def test_capacity_cannot_hide_another_resource_or_error(retry, second):
    payload = capacity_error()
    another = {"code": "Conflict", "target": PLAN, "message": MESSAGE}
    if second == "other-rg":
        another["target"] = PLAN.replace("project-rg", "another-rg")
    elif second == "unknown-conflict":
        another["message"] = "A different operation failed."
    else:
        another["extendedcode"] = "99999"
    payload["error"]["details"].append(another)
    assert not retry.is_plan_capacity_error(json.dumps(payload), SUB)


@pytest.mark.parametrize("payload", [
    '{"code":"Conflict","Code":"AuthorizationFailed"}', "null", "[]",
    '{"code":"Conflict","details":[null]}',
    '{"code":"Conflict","message":"No available instances to satisfy this request."}',
])
def test_incomplete_duplicate_or_malformed_evidence_is_terminal(retry, payload):
    assert not retry.is_plan_capacity_error(payload, SUB)


@pytest.mark.parametrize("kind", ["policy", "quota", "auth", "other-conflict", "other-plan", "other-sub",
                                "site", "missing-target", "malformed", "empty", "unknown"])
def test_noncapacity_mixed_or_unscoped_failures_do_not_retry(retry, kind):
    payload = capacity_error()
    leaf = payload["error"]["details"][0]["details"][0]["details"][0]
    if kind in {"policy", "quota", "auth", "unknown"}:
        code = {"policy": "RequestDisallowedByPolicy", "quota": "QuotaExceeded",
                "auth": "AuthorizationFailed", "unknown": "Unknown"}[kind]
        payload["error"]["details"].append({"code": code, "message": "stop"})
    elif kind == "other-conflict":
        leaf["message"] = json.dumps({"Code": "Conflict", "Message": "Another operation is in progress."})
    elif kind == "other-plan":
        leaf["target"] = PLAN + "-other"
    elif kind == "other-sub":
        leaf["target"] = PLAN.replace(SUB, "22222222-2222-2222-2222-222222222222")
    elif kind == "site":
        leaf["target"] = RG + "/providers/Microsoft.Web/sites/logic-app"
    elif kind == "missing-target":
        leaf.pop("target")
    text = json.dumps(payload)
    if kind == "malformed":
        text = text[:-4]
    elif kind == "empty":
        text = ""
    assert not retry.is_plan_capacity_error(text, SUB)


@pytest.fixture
def command(tmp_path):
    template = tmp_path / "11-integration.bicep"
    template.write_text("targetScope = 'subscription'\n", encoding="utf-8")
    parameters = tmp_path / "network.json"
    parameters.write_text('{"parameters":{}}', encoding="utf-8")
    return ["az", "deployment", "sub", "create", "--name", "unit-68-integration", "--subscription", SUB,
            "--location", "swedencentral", "--template-file", str(template),
            "--parameters", "@" + str(parameters), "--parameters", "skuLogicAppsDev=WS1",
            "--parameters", "env=dev", "--parameters", "privateValue=unit-secret",
            "--parameters", "tagsProject=" + json.dumps({"owner": "unit 'quoted' & data", "list": ["a", "b"]}),
            "--parameters", "enableLogicApps=true", "--parameters", "workerCount=1"]


@pytest.mark.parametrize("failures", [0, 1, 2, 3])
def test_retry_preserves_exact_command_and_has_bounded_wait(retry, command, monkeypatch, capsys, failures):
    error = "ERROR: " + json.dumps(capacity_error())
    outcomes = [subprocess.CompletedProcess([], 7, "", error)] * failures
    if failures < 3:
        outcomes.append(subprocess.CompletedProcess([], 0, '{"properties":{"provisioningState":"Succeeded"}}', ""))
    execute = Mock(side_effect=outcomes)
    sleep = Mock()
    monkeypatch.setattr(retry.subprocess, "run", execute)
    monkeypatch.setattr(retry.time, "sleep", sleep)
    monkeypatch.setattr(retry.shutil, "which", lambda name: "offline-az")
    assert retry.deploy(["offline-az", *command[1:]], SUB, {}) == (7 if failures == 3 else 0)
    assert execute.call_count == min(failures + 1, 3)
    assert all(call.args[0] == ["offline-az", *command[1:]] for call in execute.call_args_list)
    assert [call.args for call in sleep.call_args_list] == [(120,)] * min(failures, 2)
    assert "unit-secret" not in capsys.readouterr().out


def test_terminal_failure_is_not_retried(retry, command, monkeypatch):
    execute = Mock(return_value=subprocess.CompletedProcess([], 9, "", '{"error":{"code":"AuthorizationFailed"}}'))
    sleep = Mock()
    monkeypatch.setattr(retry.subprocess, "run", execute)
    monkeypatch.setattr(retry.time, "sleep", sleep)
    monkeypatch.setattr(retry.shutil, "which", lambda name: "offline-az")
    assert retry.deploy(["offline-az", *command[1:]], SUB, {}) == 9
    assert execute.call_count == 1 and not sleep.called


def test_changed_parameter_file_blocks_the_next_attempt(retry, command, monkeypatch):
    execute = Mock(return_value=subprocess.CompletedProcess([], 7, "", "ERROR: " + json.dumps(capacity_error())))
    path = Path(command[command.index("--parameters") + 1][1:])
    monkeypatch.setattr(retry.subprocess, "run", execute)
    monkeypatch.setattr(retry.time, "sleep", lambda delay: path.write_text('{"changed":true}'))
    monkeypatch.setattr(retry.shutil, "which", lambda name: "offline-az")
    subscription, inputs = retry.command_inputs(command)
    with pytest.raises(ValueError, match="changed"):
        retry.deploy(["offline-az", *command[1:]], subscription, inputs)
    assert execute.call_count == 1


@pytest.mark.parametrize("parameter", ["--template-file", "--parameters"])
def test_referenced_inputs_must_be_readable_before_deploying(retry, command, monkeypatch, parameter):
    value = command[command.index(parameter) + 1]
    Path(value[1:] if value.startswith("@") else value).unlink()
    execute = Mock()
    monkeypatch.setattr(retry.subprocess, "run", execute)
    with pytest.raises(OSError):
        retry.run(command)
    assert not execute.called


@pytest.mark.parametrize("change", ["wrong-command", "no-subscription", "no-wait", "wrong-template"])
def test_unsupported_commands_fail_before_azure(retry, command, monkeypatch, change):
    if change == "wrong-command":
        command[1:4] = ["group", "create"]
    elif change == "no-subscription":
        index = command.index("--subscription")
        del command[index:index + 2]
    elif change == "no-wait":
        command.append("--no-wait")
    else:
        command[command.index("--template-file") + 1] = "another.bicep"
    execute = Mock()
    monkeypatch.setattr(retry.subprocess, "run", execute)
    with pytest.raises(ValueError):
        retry.run(command)
    assert not execute.called


def test_compilation_failure_is_not_retried_or_deployed(retry, command, monkeypatch):
    execute = Mock(return_value=subprocess.CompletedProcess([], 4, "", "Compilation failed"))
    sleep = Mock()
    monkeypatch.setattr(retry.subprocess, "run", execute)
    monkeypatch.setattr(retry.time, "sleep", sleep)
    monkeypatch.setattr(retry.shutil, "which", lambda name: "offline-az")
    assert retry.run(command) == 4
    assert execute.call_count == 1 and not sleep.called
    assert execute.call_args.args[0][1:3] == ["bicep", "build"]


@pytest.mark.parametrize("value", ["[]", "null", '{"parameters":[]}'])
def test_malformed_parameter_file_stops_before_deployment(retry, command, monkeypatch, value):
    path = Path(command[command.index("--parameters") + 1][1:])
    path.write_text(value)
    execute = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(TEMPLATE), ""))
    monkeypatch.setattr(retry.subprocess, "run", execute)
    monkeypatch.setattr(retry.shutil, "which", lambda name: "offline-az")
    with pytest.raises(ValueError, match="object"):
        retry.run(command)
    assert execute.call_count == 1


@pytest.mark.parametrize("provider", ["ado", "github"])
def test_provider_integration_uses_wrapper_and_propagates_failure(tmp_path, provider):
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    executable = str(bash) if bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash required")
    settings = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"
    if provider == "ado":
        path = settings / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
        steps = yaml.safe_load(path.read_text(encoding="utf-8"))["steps"]
        step = next(item for item in steps if item.get("displayName") == "68-integration")
        script = step["inputs"]["inlineScript"]
    else:
        path = settings / "github-actions/infra-project-phase.yml"
        steps = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["deploy-project"]["steps"]
        step = next(item for item in steps if item.get("name") == "68-integration")
        script = step["run"]
    assert "deploy-integration-with-retry.py -- az deployment sub create" in script
    assert not step.get("continueOnError") and "continue-on-error" not in step
    # Run the actual task body; replace CI variables with inert offline values.
    script = re.sub(r"\$\([A-Za-z_][A-Za-z0-9_.]*\)|\$\{\{.*?\}\}", "unit", script)
    prefix = 'az() { [[ "$1 $2" == "account set" ]] || return 91; }\npython() { printf "WRAPPER:%s\\n" "$1"; return 7; }\n'
    result = subprocess.run([executable, "--noprofile", "--norc", "-c", prefix + script],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 7, result.stderr
    assert "WRAPPER:" in result.stdout


@pytest.mark.parametrize("outcome,expected_exit,attempts", [("success", 0, 3), ("exhausted", 7, 3), ("terminal", 9, 1)])
def test_actual_cli_wrapper_preserves_arguments_and_final_exit_code(tmp_path, command, outcome, expected_exit, attempts):
    stub = tmp_path / "mock_az.py"
    stub.write_text(
        "import json, os, pathlib, sys\n"
        "root=pathlib.Path(os.environ['PLAN_RETRY_TEST_ROOT'])\n"
        "if sys.argv[1:3]==['bicep','build']:\n"
        "    print((root/'compiled.json').read_text());sys.exit(0)\n"
        "log=root/'calls.jsonl'\n"
        "count=len(log.read_text().splitlines()) if log.exists() else 0\n"
        "params=pathlib.Path(sys.argv[sys.argv.index('--parameters')+1][1:])\n"
        "with log.open('a') as stream: stream.write(json.dumps({'args':sys.argv[1:],'parameters':json.loads(params.read_text())})+'\\n')\n"
        "mode=os.environ['PLAN_RETRY_TEST_OUTCOME']\n"
        "if mode=='terminal':\n"
        "    print('{\"error\":{\"code\":\"AuthorizationFailed\"}}',file=sys.stderr);sys.exit(9)\n"
        "if mode=='success' and count==2:\n"
        "    print('{\"properties\":{\"provisioningState\":\"Succeeded\"}}');sys.exit(0)\n"
        "print('ERROR: '+(root/'capacity.json').read_text(),file=sys.stderr)\n"
        "sys.exit(7)\n", encoding="utf-8",
    )
    (tmp_path / "capacity.json").write_text(json.dumps(capacity_error()), encoding="utf-8")
    (tmp_path / "compiled.json").write_text(json.dumps(TEMPLATE), encoding="utf-8")
    fake_az = tmp_path / ("az.cmd" if os.name == "nt" else "az")
    if os.name == "nt":
        fake_az.write_text(f'@echo off\n"{sys.executable}" "{stub}" %*\n', encoding="utf-8")
    else:
        import shlex
        fake_az.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(stub))} \"$@\"\n")
        fake_az.chmod(0o755)
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import os, pathlib, runpy, shutil, sys, time\n"
        "root=pathlib.Path(os.environ['PLAN_RETRY_TEST_ROOT'])\n"
        "shutil.which=lambda name: str(root/('az.cmd' if os.name=='nt' else 'az'))\n"
        "def sleep(seconds):\n"
        "    with (root/'waits.txt').open('a') as stream: stream.write(str(seconds)+'\\n')\n"
        "time.sleep=sleep\n"
        "sys.argv=sys.argv[1:]\n"
        "runpy.run_path(sys.argv[0],run_name='__main__')\n", encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(launcher), str(SCRIPT), "--", *command], capture_output=True, text=True,
        timeout=30, env={**os.environ, "PLAN_RETRY_TEST_ROOT": str(tmp_path), "PLAN_RETRY_TEST_OUTCOME": outcome},
    )
    assert result.returncode == expected_exit, result.stderr
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert len(calls) == attempts and calls == [calls[0]] * attempts
    actual = calls[0]["args"]
    assert actual[:3] == ["deployment", "sub", "create"]
    for key in ("--name", "--subscription", "--location"):
        assert actual[actual.index(key) + 1] == command[command.index(key) + 1]
    assert actual.count("--parameters") == 1 and "unit-secret" not in " ".join(actual)
    assert calls[0]["parameters"] == {"parameters": {
        "skuLogicAppsDev": {"value": "WS1"}, "env": {"value": "dev"},
        "privateValue": {"value": "unit-secret"},
        "tagsProject": {"value": {"owner": "unit 'quoted' & data", "list": ["a", "b"]}},
        "enableLogicApps": {"value": True}, "workerCount": {"value": 1},
    }}
    assert not Path(actual[actual.index("--parameters") + 1][1:]).exists()
    assert not Path(actual[actual.index("--template-file") + 1]).exists()
    waits = tmp_path / "waits.txt"
    assert (waits.read_text().splitlines() if waits.exists() else []) == ["120"] * (attempts - 1)
