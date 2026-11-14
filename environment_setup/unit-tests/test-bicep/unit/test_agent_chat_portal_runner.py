"""Offline contracts for the prepared-VM portal runner; never use a real Azure login."""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parents[4]
ADAPTER = ROOT / "bootstrap/lib/agent_chat_portal.py"
SCRIPT = ROOT / "portal/agent-chat/run.sh"
SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"
IDENTITY = "33333333-3333-4333-8333-333333333333"
APP = "aifactory-agent-project012-dev"
GROUP = "spider-esml-project012-sdc-dev-001-rg"
RESOURCE = f"/subscriptions/{SUB}/resourceGroups/{GROUP}/providers/Microsoft.App/containerApps/{APP}"
FQDN = f"{APP}.private.swedencentral.azurecontainerapps.io"
READY = {"status": "ready", "checks": {"authentication": "configured", "knowledge": "ready"}}


@pytest.fixture
def portal(monkeypatch):
    monkeypatch.syspath_prepend(str(ADAPTER.parent))
    monkeypatch.syspath_prepend(str(ROOT / "usecase_code/40-agent-factory"))
    spec = importlib.util.spec_from_file_location("agent_chat_portal_test", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / "consumer with spaces;literal"
    root.mkdir()
    (root / ".git").mkdir()
    accelerator = root / "azure-enterprise-scale-ml"
    for relative in ("bootstrap/lib/agent_chat_entry.py", "bootstrap/lib/agent_chat_portal.py",
                     "usecase_code/40-agent-factory/46-factory-chat-agent/deploy.py",
                     "usecase_code/40-agent-factory/47-aifactory-agent-live-voice/deploy.py"):
        target = accelerator / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# prepared checkout\n", encoding="utf-8")
    values = {
        "project_number_000": "012", "dev_sub_id": SUB, "tenantId": TENANT,
        "admin_location": "swedencentral", "admin_aifactoryPrefixRG": "spider-",
        "projectPrefix": "esml-", "admin_locationSuffix": "sdc", "admin_aifactorySuffixRG": "-001",
        "projectSuffix": "-rg", "modelGPTXName": "gpt-5.4-mini",
        "enableContainerApps": True, "enableAIFoundry": True, "enableAISearch": True,
        "aifactoryAgentEntraAppId": IDENTITY, "aifactoryAgentReaderObjectIds": IDENTITY,
    }
    config = root / "aifactory/variables.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"dev": values}), encoding="utf-8")
    home = tmp_path / "runner-home"
    home.mkdir()
    shared = home / ".azure"
    shared.mkdir()
    (shared / "sentinel").write_text("operator login", encoding="utf-8")
    tools = tmp_path / "prepared-tools"
    tools.mkdir()
    bicep = tools / ("bicep.exe" if os.name == "nt" else "bicep")
    bicep.write_text("offline PATH discovery fixture", encoding="utf-8")
    bicep.chmod(0o755)
    env = {
        **os.environ, "HOME": str(home), "AZURE_CONFIG_DIR": str(shared),
        "PATH": str(tools) + os.pathsep + os.environ.get("PATH", ""),
        "AZURE_BICEP_USE_BINARY_FROM_PATH": "false",
        "AIF_CONSUMER_ROOT": str(root), "AIF_PROJECT_NUMBER": "012", "AIF_PYTHON": sys.executable,
        "AIF_IDENTITY_CLIENT_ID": IDENTITY, "AIF_SUBSCRIPTION_ID": SUB, "AIF_TENANT_ID": TENANT,
        "AIF_CONFIGURATION_PATH": "", "AIF_RUN_ID": "rerun;$(not-executed)",
    }
    return SimpleNamespace(env=env, root=root, config=config, shared=shared, values=values)


class Harness:
    def __init__(self):
        self.events = []
        self.commands = []
        self.contexts = []
        self.account = {"id": SUB, "tenantId": TENANT}
        self.app = {"id": RESOURCE, "properties": {
            "provisioningState": "Succeeded", "configuration": {"ingress": {"fqdn": FQDN}}}}
        self.chat_result = {"mode": "apply", "status": "unchanged", "mutations": False}
        self.voice_result = {"mode": "apply", "mutations": True, "outputs": {
            "scope": "project012-dev", "voice": True, "app": {"fqdn": FQDN, "deployment_state": "Succeeded"}}}
        self.fail_validation = None
        self.fail_command = None

    def stage(self, name):
        def run(args, environ):
            self.events.append(f"{name}:{args.command}")
            assert environ["enableFactoryChatAgent"] == "true"
            assert environ["enableAIFactoryAgentLiveVoice"] == "true"
            assert environ["deleteAllForProject"] == "false"
            if args.command == "validate":
                if self.fail_validation == name:
                    raise ValueError("incomplete configuration")
                return {"mode": "validated", "mutations": False}
            assert args.command == "apply" and args.apply and not args.skip_knowledge
            self.contexts.append(dict(os.environ))
            return self.chat_result if name == "chat" else self.voice_result
        return run

    def command(self, args, **kwargs):
        assert isinstance(args, list) and not kwargs.get("shell")
        env = kwargs.get("env", os.environ)
        self.contexts.append(dict(env))
        self.commands.append(args)
        verb = args[1:3]
        self.events.append("az:" + ":".join(verb))
        if self.fail_command and verb == self.fail_command:
            return SimpleNamespace(returncode=17, stdout="", stderr="denied")
        if verb == ["account", "show"]:
            output = self.account
        elif args[1] == "rest":
            output = self.app
        else:
            output = {}
        return SimpleNamespace(returncode=0, stdout=json.dumps(output), stderr="")

    def readiness(self, fqdn):
        self.events.append("ready")
        assert fqdn == FQDN
        return READY

    def invoke(self, portal, prepared):
        return portal.main(prepared.env, chat_runner=self.stage("chat"), voice_runner=self.stage("voice"),
                           run=self.command, readiness=self.readiness)


def test_prevalidates_both_stages_then_uami_login_apply_and_verified_readiness(portal, prepared, capsys):
    harness = Harness()
    assert harness.invoke(portal, prepared) == 0
    assert harness.events == ["chat:validate", "voice:validate", "az:login:--identity",
                              "az:account:set", "az:account:show", "chat:apply", "voice:apply",
                              "az:rest:--method", "ready"]
    assert "--client-id" in harness.commands[0] and IDENTITY in harness.commands[0]
    assert "--subscription" in harness.commands[1] and SUB in harness.commands[1]
    assert f"https://management.azure.com{RESOURCE}?api-version=2025-01-01" in harness.commands[-1]
    assert "https://" + FQDN in capsys.readouterr().out
    isolated = {ctx["AZURE_CONFIG_DIR"] for ctx in harness.contexts}
    assert len(isolated) == 1 and str(prepared.shared) not in isolated
    assert all(not Path(path).exists() for path in isolated)
    assert all(ctx["RUNNER_TEMP"] != prepared.env.get("RUNNER_TEMP") for ctx in harness.contexts)
    assert all(ctx["AZURE_BICEP_USE_BINARY_FROM_PATH"] == "true" for ctx in harness.contexts)
    assert (prepared.shared / "sentinel").read_text() == "operator login"


@pytest.mark.parametrize("name,value", [
    ("AIF_PROJECT_NUMBER", "000"), ("AIF_PROJECT_NUMBER", "1"),
    ("AIF_PROJECT_NUMBER", "012;echo bad"), ("AIF_IDENTITY_CLIENT_ID", "not-a-uuid"),
    ("AIF_SUBSCRIPTION_ID", "bad"), ("AIF_TENANT_ID", ""), ("AIF_RUN_ID", ""),
    ("AIF_CONSUMER_ROOT", "relative"), ("AIF_PYTHON", "python3"),
    ("AIF_CONFIGURATION_PATH", "missing/variables.json"),
])
def test_invalid_input_fails_before_login(portal, prepared, name, value):
    prepared.env[name] = value
    harness = Harness()
    assert harness.invoke(portal, prepared) == 2
    assert not harness.commands


@pytest.mark.parametrize("key,value", [("dev_sub_id", IDENTITY), ("tenantId", IDENTITY),
                                      ("project_number_000", "013")])
def test_config_target_must_match_portal_selection_before_login(portal, prepared, key, value):
    prepared.values[key] = value
    prepared.config.write_text(json.dumps({"dev": prepared.values}))
    harness = Harness()
    assert harness.invoke(portal, prepared) == 2
    assert not harness.commands


def test_rejects_ephemeral_pipeline_checkout(portal, prepared):
    moved = prepared.root.parent / "_work" / "1" / "s"
    moved.parent.mkdir(parents=True)
    prepared.root.rename(moved)
    prepared.env["AIF_CONSUMER_ROOT"] = str(moved)
    harness = Harness()
    assert harness.invoke(portal, prepared) == 2
    assert not harness.commands


def test_tmp_path_component_is_not_evidence_of_an_ephemeral_checkout(portal, prepared):
    # Linux pytest uses /tmp; a mount/directory name alone cannot establish checkout lifetime.
    moved = prepared.root.parent / "tmp" / "maintained-consumer"
    moved.parent.mkdir()
    prepared.root.rename(moved)
    prepared.env["AIF_CONSUMER_ROOT"] = str(moved)
    harness = Harness()
    assert harness.invoke(portal, prepared) == 0


def test_python_must_be_prepared_312_or_newer(portal, prepared, monkeypatch):
    monkeypatch.setattr(portal.sys, "version_info", (3, 11, 9))
    harness = Harness()
    assert harness.invoke(portal, prepared) == 2
    assert not harness.commands


def test_requires_preinstalled_bicep_on_path_before_login(portal, prepared, tmp_path, capsys):
    empty = tmp_path / "empty-tools"
    empty.mkdir()
    prepared.env["PATH"] = str(empty)
    harness = Harness()
    assert harness.invoke(portal, prepared) == 2
    assert not harness.commands
    assert "bicep" in capsys.readouterr().err.lower()


def test_voice_validation_fails_before_chat_mutates(portal, prepared):
    harness = Harness()
    harness.fail_validation = "voice"
    assert harness.invoke(portal, prepared) == 2
    assert harness.events == ["chat:validate", "voice:validate"]


def test_real_deployers_validate_offline_without_session_or_operator_install(portal, prepared, monkeypatch):
    launcher = portal.entry.launcher
    monkeypatch.setattr(portal.entry, "launcher", lambda root, folder: launcher(ROOT, folder))
    prepared.values["enableAISearch"] = False
    prepared.config.write_text(json.dumps({"dev": prepared.values}))
    harness = Harness()
    assert portal.main(prepared.env, run=harness.command, readiness=harness.readiness) == 2
    assert not harness.commands


def test_real_validation_does_not_borrow_missing_project_values_from_shared_runner(portal, prepared, monkeypatch):
    launcher = portal.entry.launcher
    monkeypatch.setattr(portal.entry, "launcher", lambda root, folder: launcher(ROOT, folder))
    prepared.values.pop("enableAISearch")
    prepared.config.write_text(json.dumps({"dev": prepared.values}))
    prepared.env["enableAISearch"] = "true"
    harness = Harness()
    harness.fail_command = ["login", "--identity"]
    assert portal.main(prepared.env, run=harness.command, readiness=harness.readiness) == 2
    assert not harness.commands


def test_existing_deployers_run_from_local_snapshot_without_writing_consumer(portal, prepared, monkeypatch):
    harness = Harness()
    loaded = []
    def launcher(root, folder):
        loaded.append(root)
        stage = harness.stage("chat" if folder.startswith("46-") else "voice")
        def run(args, environ):
            if args.command == "apply":
                (root / portal.entry.SUBMODULE / "generated-build-artifact").write_text("local build")
            return stage(args, environ)
        return run
    monkeypatch.setattr(portal.entry, "launcher", launcher)
    before = {path.relative_to(prepared.root) for path in prepared.root.rglob("*")}
    assert portal.main(prepared.env, run=harness.command, readiness=harness.readiness) == 0
    assert loaded[:2] == [prepared.root, prepared.root]
    assert loaded[2] != prepared.root and loaded[2] == loaded[3]
    assert not loaded[2].exists()
    assert {path.relative_to(prepared.root) for path in prepared.root.rglob("*")} == before


@pytest.mark.parametrize("staged", [False, True])
def test_real_live_voice_engine_uses_launcher_source_even_with_cached_factory_module(
        portal, prepared, monkeypatch, tmp_path, staged):
    maintained_runner = portal.entry.launcher(ROOT, portal.STAGES[1])
    engine_type = maintained_runner.__globals__["LiveVoiceIntegration"]
    if staged:
        consumer = tmp_path / "isolated-source"
        accelerator = consumer / portal.entry.SUBMODULE
        deployment = accelerator / portal.entry.AGENT_FACTORY / portal.STAGES[1] / "deploy.py"
        deployment.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / portal.entry.AGENT_FACTORY / portal.STAGES[1] / "deploy.py", deployment)
        selected_runner = portal.entry.launcher(consumer, portal.STAGES[1])
    else:
        accelerator = ROOT
        selected_runner = maintained_runner
    assert selected_runner.__globals__["LiveVoiceIntegration"] is engine_type
    expected_agent = accelerator / portal.entry.AGENT_FACTORY / "40-aifactory-agent"
    wheels = tmp_path / "downloaded-wheels"
    wheels.mkdir()
    (wheels / "example.whl").write_bytes(b"offline fixture")
    observed = []
    def inspect_engine(self, request, *, apply, skip_knowledge):
        observed.append(self)
        assert self.repository_root == accelerator
        assert self.agent_dir == expected_agent
        if staged:
            self._stage_wheels(wheels)
            assert (expected_agent / ".build/wheels/example.whl").read_bytes() == b"offline fixture"
        return {"mode": "apply", "mutations": True}
    monkeypatch.setattr(engine_type, "run", inspect_engine)
    _, _, values = portal.inputs(prepared.env)
    values.update({"RUNNER_TEMP": str(tmp_path / "work"), "RUNNER_TOOL_CACHE": str(tmp_path / "tools")})
    args = SimpleNamespace(command="apply", apply=True, skip_knowledge=False)
    result = selected_runner(args, values, session_factory=lambda *args: object(), access_factory=lambda _: None)
    assert result["mode"] == "apply" and len(observed) == 1


@pytest.mark.parametrize("transient", [".claude", ".scout"])
def test_local_snapshot_excludes_assistant_worktrees(portal, prepared, monkeypatch, transient):
    unrelated = prepared.root / portal.entry.SUBMODULE / transient / "worktrees/unrelated/source"
    unrelated.mkdir(parents=True)
    (unrelated / "sentinel").write_text("do not copy")
    harness = Harness()
    def launcher(root, folder):
        if root != prepared.root:
            assert not (root / portal.entry.SUBMODULE / transient).exists()
        return harness.stage("chat" if folder.startswith("46-") else "voice")
    monkeypatch.setattr(portal.entry, "launcher", launcher)
    assert portal.main(prepared.env, run=harness.command, readiness=harness.readiness) == 0
    assert (unrelated / "sentinel").read_text() == "do not copy"


@pytest.mark.parametrize("stage,result", [
    ("chat", {"mode": "apply", "status": "skipped"}),
    ("chat", {"mode": "apply"}),
    ("voice", {"mode": "apply", "mutations": False}),
])
def test_success_shaped_but_not_completed_stage_is_rejected(portal, prepared, stage, result):
    harness = Harness()
    getattr(harness, f"{stage}_result").update(result)
    if stage == "chat" and "status" not in result:
        harness.chat_result.pop("status")
    assert harness.invoke(portal, prepared) == 1
    assert "ready" not in harness.events


@pytest.mark.parametrize("field", ["id", "tenantId"])
def test_wrong_authenticated_account_never_deploys(portal, prepared, field):
    harness = Harness()
    harness.account[field] = IDENTITY
    assert harness.invoke(portal, prepared) == 1
    assert "chat:apply" not in harness.events
    assert all(not Path(ctx["AZURE_CONFIG_DIR"]).exists() for ctx in harness.contexts)


@pytest.mark.parametrize("stage", ["chat", "voice"])
@pytest.mark.parametrize("field,value", [
    ("dev_test_prod_sub_id", IDENTITY), ("tenantId", IDENTITY),
    ("project_number_000", "013"), ("dev_test_prod", "prod"),
    ("projectResourceGroup", "other-project-rg"), ("admin_aifactoryPrefixRG", "other-"),
    ("aifactoryAgentContainerAppsEnvironment", "other-environment"),
])
def test_config_change_after_validation_is_rejected_before_affected_stage_mutates(
        portal, prepared, monkeypatch, stage, field, value):
    harness = Harness()
    _, _, validated = portal.inputs(prepared.env)
    def changed_main(args, *, chat_runner, voice_runner):
        command = SimpleNamespace(command="apply", apply=True, skip_knowledge=False)
        current = {**os.environ, **validated}
        if stage == "voice":
            chat_runner(command, current)
        document = json.loads(prepared.config.read_text())
        document["dev"]["dev_sub_id" if field == "dev_test_prod_sub_id" else field] = value
        prepared.config.write_text(json.dumps(document))
        current[field] = value
        if stage == "chat":
            chat_runner(command, current)
        voice_runner(command, current)
        return 0
    monkeypatch.setattr(portal.entry, "main", changed_main)
    assert harness.invoke(portal, prepared) == 1
    assert f"{stage}:apply" not in harness.events
    assert "ready" not in harness.events


def test_unrelated_configuration_metadata_can_change_without_a_hash_gate(portal, prepared, monkeypatch):
    harness = Harness()
    original_main = portal.entry.main
    def changed_main(args, **runners):
        document = json.loads(prepared.config.read_text())
        document["dev"]["operatorNote"] = "metadata updated after validation"
        prepared.config.write_text(json.dumps(document))
        return original_main(args, **runners)
    monkeypatch.setattr(portal.entry, "main", changed_main)
    assert harness.invoke(portal, prepared) == 0


@pytest.mark.parametrize("stage", ["chat", "voice"])
@pytest.mark.parametrize("mode", ["skipped", "skipped_incomplete", "plan"])
def test_not_applied_stage_is_a_failure_not_green(portal, prepared, stage, mode):
    harness = Harness()
    setattr(harness, f"{stage}_result", {"mode": mode, "mutations": False})
    assert harness.invoke(portal, prepared) == 1
    assert "ready" not in harness.events
    if stage == "chat":
        assert "voice:apply" not in harness.events


@pytest.mark.parametrize("app", [
    {}, {"fqdn": FQDN, "deployment_state": "Failed"},
    {"fqdn": "evil.example", "deployment_state": "Succeeded"},
    {"fqdn": f"{FQDN}/redirect", "deployment_state": "Succeeded"},
    {"fqdn": f"{FQDN}@evil.example", "deployment_state": "Succeeded"},
])
def test_invalid_application_outputs_never_probe(portal, prepared, app):
    harness = Harness()
    harness.voice_result["outputs"]["app"] = app
    assert harness.invoke(portal, prepared) == 1
    assert "ready" not in harness.events


def test_fqdn_must_match_resource_in_selected_project(portal, prepared):
    harness = Harness()
    harness.app["properties"]["configuration"]["ingress"]["fqdn"] = "other.private.azurecontainerapps.io"
    assert harness.invoke(portal, prepared) == 1
    assert "ready" not in harness.events


def test_failed_login_preserves_shared_session_and_never_falls_back(portal, prepared):
    harness = Harness()
    harness.fail_command = ["login", "--identity"]
    assert harness.invoke(portal, prepared) == 1
    assert len(harness.commands) == 1
    assert (prepared.shared / "sentinel").read_text() == "operator login"
    assert all(not Path(ctx["AZURE_CONFIG_DIR"]).exists() for ctx in harness.contexts)


def test_unavailable_readiness_makes_entire_run_fail(portal, prepared):
    harness = Harness()
    def unavailable(fqdn):
        raise RuntimeError("readiness deadline exceeded")
    harness.readiness = unavailable
    assert harness.invoke(portal, prepared) == 1


class Response(io.BytesIO):
    status = 200

    def __init__(self, document):
        super().__init__(json.dumps(document).encode())


def test_readiness_retries_transient_startup_and_checks_json_without_credentials(portal):
    outcomes = [HTTPError("https://" + FQDN, 503, "starting", {}, None),
                URLError(socket.gaierror(socket.EAI_AGAIN, "dns starting")),
                Response({"status": "not_ready", "checks": {"knowledge": "unavailable"}}), Response(READY)]
    calls, sleeps = [], []
    def open_url(request, timeout):
        calls.append(request)
        result = outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
    assert portal.wait_ready(FQDN, open_url=open_url, attempts=4, delay=1, sleep=sleeps.append) == READY
    assert sleeps == [1, 1, 1]
    assert all(request.full_url == f"https://{FQDN}/health/ready" for request in calls)
    assert all(not request.has_header("Authorization") for request in calls)


@pytest.mark.parametrize("document", [
    {"status": "not_ready"}, {"status": "ready", "checks": {"authentication": "unconfigured", "knowledge": "ready"}},
    {"status": "ready", "checks": {"authentication": "configured", "knowledge": "unavailable"}},
])
def test_http_200_unhealthy_body_is_not_success(portal, document):
    with pytest.raises(RuntimeError, match="readiness"):
        portal.wait_ready(FQDN, open_url=lambda *args, **kwargs: Response(document),
                          attempts=2, delay=0, sleep=lambda _: None)


@pytest.mark.parametrize("error", [
    HTTPError("https://" + FQDN, 401, "unauthorized", {}, None),
    HTTPError("https://" + FQDN, 302, "redirect", {"Location": "https://evil.example"}, None),
    URLError(ssl.SSLCertVerificationError("untrusted certificate")),
])
def test_readiness_does_not_retry_auth_redirect_or_tls_failure(portal, error):
    calls = []
    def failed(*args, **kwargs):
        calls.append(1)
        raise error
    with pytest.raises(RuntimeError):
        portal.wait_ready(FQDN, open_url=failed, attempts=3, sleep=lambda _: pytest.fail("unexpected retry"))
    assert calls == [1]


def test_no_redirect_handler_refuses_new_destination(portal):
    with pytest.raises(RuntimeError, match="redirect"):
        portal.NoRedirects().redirect_request(None, None, 302, "redirect", {}, "https://evil.example")


def test_readiness_does_not_retry_an_unknown_response_contract(portal):
    with pytest.raises(RuntimeError, match="readiness"):
        portal.wait_ready(FQDN, open_url=lambda *args, **kwargs: Response({"status": "unexpected"}),
                          sleep=lambda _: pytest.fail("unexpected retry"))


def test_thin_bash_adapter_preserves_literal_environment_and_error_exit(tmp_path):
    bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
    executable = str(bash) if bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("bash unavailable")
    assert SCRIPT.is_file()
    root = tmp_path / "consumer with spaces;literal"
    adapter = root / "azure-enterprise-scale-ml/bootstrap/lib/agent_chat_portal.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("# fake adapter")
    fake_python = tmp_path / "prepared python"
    fake_python.write_text('#!/bin/bash\nprintf "%s\\n" "$@" "$AIF_RUN_ID"\nexit 23\n', encoding="utf-8")
    fake_python.chmod(0o755)
    def linux(path):
        text = path.resolve().as_posix()
        return "/" + text[0].lower() + text[2:] if len(text) > 1 and text[1] == ":" else text
    env = {**os.environ, "AIF_PYTHON": linux(fake_python), "AIF_CONSUMER_ROOT": linux(root),
           "AIF_RUN_ID": "literal;$(touch should-not-exist)"}
    result = subprocess.run([executable, linux(SCRIPT)], env=env, text=True, capture_output=True, cwd=tmp_path)
    assert result.returncode == 23, result.stderr
    assert "-B" in result.stdout
    assert "literal;$(touch should-not-exist)" in result.stdout
    assert not (tmp_path / "should-not-exist").exists()
