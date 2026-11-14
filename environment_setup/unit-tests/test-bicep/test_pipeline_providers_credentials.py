"""Provider credentials remain local; all Azure calls are intercepted."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))
import pipeline_credentials as credentials
import pipeline_dispatch as dispatch


SECRET_ID = "https://external-seeding.vault.azure.net/secrets/provider-token/" + "a" * 32
TOKEN = "offline-sensitive-provider-value"


@pytest.fixture(autouse=True)
def forbid_live_calls(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live network forbidden"))
    monkeypatch.setattr(credentials.subprocess, "run", lambda *_a, **_k: pytest.fail("Unmocked subprocess"))


def azure_runner(calls, *, account=True, token=TOKEN, reference=SECRET_ID, returned_id=SECRET_ID, **metadata):
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["capture_output"] and kwargs["text"] and not kwargs.get("shell")
        assert TOKEN not in " ".join(command)
        if command[1:3] == ["account", "show"]:
            return subprocess.CompletedProcess(command, 0 if account else 1, "{}", TOKEN)
        assert command[1:4] == ["keyvault", "secret", "show"]
        assert command[command.index("--id") + 1] == reference
        assert "--debug" not in command and "--only-show-errors" in command
        return subprocess.CompletedProcess(command, 0, json.dumps(
            {"id": returned_id, "value": token, **metadata}), TOKEN)
    return run


@pytest.mark.parametrize("provider,target", [("gha", "GH_TOKEN"), ("ado", "AIFACTORY_STATE_TOKEN")])
def test_seeded_token_is_only_in_transient_child_environment(tmp_path, provider, target, capsys):
    calls = []
    before = {"ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID": SECRET_ID,
              "GH_TOKEN": "job-read-token", "SYSTEM_ACCESSTOKEN": "job-read-token",
              "GITHUB_ENV": str(tmp_path / "github-env"), "GITHUB_OUTPUT": str(tmp_path / "github-output")}
    environment = dict(before)
    child = credentials.provider_environment(provider, environ=environment, runner=azure_runner(calls))
    assert environment == before
    assert child[target] == TOKEN
    if provider == "ado":
        assert child["SYSTEM_ACCESSTOKEN"] == TOKEN
    assert [command[1] for command in calls] == ["account", "keyvault"]
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err
    assert list(tmp_path.iterdir()) == [], "No token, export, output or artifact files"


@pytest.mark.parametrize("provider,environment,target", [
    ("gha", {"GH_TOKEN": TOKEN}, "GH_TOKEN"),
    ("gha", {"ESAF_PROVIDER_TOKEN": TOKEN}, "GH_TOKEN"),
    ("ado", {"SYSTEM_ACCESSTOKEN": TOKEN}, "AIFACTORY_STATE_TOKEN"),
    ("ado", {"ESAF_PROVIDER_TOKEN": TOKEN, "SYSTEM_ACCESSTOKEN": "job-read"}, "AIFACTORY_STATE_TOKEN"),
])
def test_protected_credentials_keep_existing_path_without_azure_reads(provider, environment, target):
    before = dict(environment)
    child = credentials.provider_environment(provider, environ=environment)
    assert child[target] == TOKEN
    assert environment == before


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_missing_protected_credential_fails_closed(provider):
    with pytest.raises(credentials.CredentialError, match="provider-token-required"):
        credentials.provider_environment(provider, environ={})


def test_undefined_optional_ado_macros_preserve_original_job_token():
    environment = {name: "$(" + name + ")" for name in (
        "ESAF_PROVIDER_CREDENTIAL_SOURCE", "ESAF_PROVIDER_TOKEN_SECRET_ID", "ESAF_PROVIDER_TOKEN")}
    environment["SYSTEM_ACCESSTOKEN"] = TOKEN
    child = credentials.provider_environment("ado", environ=environment)
    assert child["AIFACTORY_STATE_TOKEN"] == TOKEN


@pytest.mark.parametrize("environment,code", [
    ({"ESAF_PROVIDER_CREDENTIAL_SOURCE": "arbitrary"}, "credential-source-invalid"),
    ({"ESAF_PROVIDER_TOKEN_SECRET_ID": SECRET_ID, "GH_TOKEN": TOKEN}, "keyvault-opt-in-required"),
    ({"ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault"}, "keyvault-secret-id-required"),
    ({"ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID":
      "https://attacker.invalid/secrets/token/" + "a" * 32}, "keyvault-secret-id-required"),
    ({"ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID":
      SECRET_ID + "?token=" + TOKEN}, "keyvault-secret-id-required"),
])
def test_invalid_reference_or_implicit_opt_in_never_calls_azure(environment, code):
    with pytest.raises(credentials.CredentialError, match=code) as error:
        credentials.provider_environment("gha", environ=environment)
    assert TOKEN not in str(error.value)


def test_no_keyvault_read_before_successful_azure_login(capsys):
    calls = []
    with pytest.raises(credentials.CredentialError, match="azure-login-required"):
        credentials.provider_environment("gha", environ={
            "ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID": SECRET_ID},
            runner=azure_runner(calls, account=False))
    assert len(calls) == 1
    assert TOKEN not in str(capsys.readouterr())


def test_unversioned_secret_uses_native_success_without_expiry_gate():
    reference = SECRET_ID.rsplit("/", 1)[0]
    child = credentials.provider_environment("gha", environ={
        "ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID": reference},
        runner=azure_runner([], reference=reference, attributes={"expires": 1}))
    assert child["GH_TOKEN"] == TOKEN


def test_derived_version_drift_warns_but_successful_native_get_is_authority(capsys):
    child = credentials.provider_environment("gha", environ={
        "ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID": SECRET_ID},
        runner=azure_runner([], returned_id=SECRET_ID.rsplit("/", 1)[0] + "/" + "b" * 32,
                            attributes={"expires": 1}))
    assert child["GH_TOKEN"] == TOKEN
    captured = capsys.readouterr()
    assert "keyvault-secret-version-drift" in captured.err
    assert TOKEN not in captured.err + captured.out


@pytest.mark.parametrize("returned_id", [
    SECRET_ID.replace("external-seeding", "different-vault"),
    SECRET_ID.replace("provider-token", "different-secret"),
    SECRET_ID.replace(".vault.azure.net", ".attacker.invalid"),
    SECRET_ID + "?credential=" + TOKEN,
])
def test_success_does_not_override_native_vault_and_secret_identity(returned_id):
    with pytest.raises(credentials.CredentialError, match="keyvault-secret-identity-mismatch"):
        credentials.provider_environment("gha", environ={
            "ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID": SECRET_ID},
            runner=azure_runner([], returned_id=returned_id))


@pytest.mark.parametrize("token", ["", "bad\nvalue", "bad\rvalue", "bad\x00value", {}, "x" * 32769],
                         ids=["empty", "lf", "cr", "nul", "object", "oversize"])
def test_invalid_secret_values_do_not_reach_child(token):
    with pytest.raises(credentials.CredentialError, match="provider-token-invalid"):
        credentials.provider_environment("gha", environ={
            "ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID": SECRET_ID},
            runner=azure_runner([], token=token))


def test_keyvault_failure_has_no_secret_stderr_or_fallback(capsys):
    def fail(command, **_):
        if command[1] == "account":
            return subprocess.CompletedProcess(command, 0, "{}", "")
        raise subprocess.CalledProcessError(1, command, output=TOKEN, stderr=TOKEN)
    with pytest.raises(credentials.CredentialError, match="keyvault-credential-unavailable") as error:
        credentials.provider_environment("gha", environ={
            "ESAF_PROVIDER_CREDENTIAL_SOURCE": "keyvault", "ESAF_PROVIDER_TOKEN_SECRET_ID": SECRET_ID,
            "GH_TOKEN": "must-not-fallback"}, runner=fail)
    assert TOKEN not in str(error.value) + str(capsys.readouterr())


def test_wrapper_child_failure_preserves_exit_code_without_exporting(monkeypatch, capsys):
    monkeypatch.setenv("ESAF_PROVIDER_TOKEN", TOKEN)
    monkeypatch.delenv("ESAF_PROVIDER_CREDENTIAL_SOURCE", raising=False)
    monkeypatch.delenv("ESAF_PROVIDER_TOKEN_SECRET_ID", raising=False)
    calls = []
    def child(command, **kwargs):
        calls.append(command)
        assert command == ["python3", "trusted.py", "execute"]
        assert kwargs["env"]["GH_TOKEN"] == TOKEN and not kwargs.get("shell")
        return subprocess.CompletedProcess(command, 7)
    monkeypatch.setattr(credentials.subprocess, "run", child)
    assert credentials.main(["--provider", "gha", "--", "python3", "trusted.py", "execute"]) == 7
    assert len(calls) == 1 and TOKEN not in str(capsys.readouterr())


def untracked(command, **kwargs):
    assert command[:2] == ["git", "-C"] and "ls-files" in command
    assert kwargs["capture_output"] and not kwargs.get("shell")
    return subprocess.CompletedProcess(command, 1, "", "")


def test_env_file_is_explicit_literal_and_exported_environment_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials.subprocess, "run", untracked)
    path = tmp_path / ".env"
    path.write_text("# local only\nGH_TOKEN='$(never-execute)'\n"
                    'export GITHUB_TOKEN="${GH_TOKEN}#literal"\nAZURE_DEVOPS_EXT_PAT=literal=value\n')
    environment = {"GH_TOKEN": "already-exported"}
    credentials.load_dispatch_env(path, environ=environment)
    assert environment == {"GH_TOKEN": "already-exported", "AZURE_DEVOPS_EXT_PAT": "literal=value"}
    empty = {}
    credentials.load_dispatch_env(path, environ=empty)
    assert empty == {"GH_TOKEN": "$(never-execute)", "GITHUB_TOKEN": "${GH_TOKEN}#literal",
                     "AZURE_DEVOPS_EXT_PAT": "literal=value"}


@pytest.mark.parametrize("exported,local", [
    ("GH_TOKEN", "GITHUB_TOKEN"), ("GITHUB_TOKEN", "GH_TOKEN"),
    ("SYSTEM_ACCESSTOKEN", "AZURE_DEVOPS_EXT_PAT"), ("AZURE_DEVOPS_EXT_PAT", "SYSTEM_ACCESSTOKEN"),
])
@pytest.mark.parametrize("value", ["already-exported", ""])
def test_exported_credentials_win_across_provider_token_aliases(tmp_path, monkeypatch, exported, local, value):
    monkeypatch.setattr(credentials.subprocess, "run", untracked)
    path = tmp_path / ".env"
    path.write_text(local + "=must-not-override")
    environment = {exported: value}
    credentials.load_dispatch_env(path, environ=environment)
    assert environment == {exported: value}


@pytest.mark.parametrize("content", [
    "1BAD=secret", "BAD-NAME=secret", "GH_TOKEN", "GH_TOKEN='unterminated",
    "GH_TOKEN=secret\nGH_TOKEN=other", "GH_TOKEN=secret\x00", "PYTHONPATH=attacker",
    "BASH_ENV=attacker", "PATH=attacker", "GH_TOKEN=secret\nnot an assignment",
])
def test_invalid_env_file_is_atomic_and_does_not_echo_values(tmp_path, monkeypatch, content):
    monkeypatch.setattr(credentials.subprocess, "run", untracked)
    path = tmp_path / ".env"
    path.write_text(content)
    environment = {"GH_TOKEN": "preserved"}
    with pytest.raises(credentials.CredentialError) as error:
        credentials.load_dispatch_env(path, environ=environment)
    assert environment == {"GH_TOKEN": "preserved"}
    assert "secret" not in str(error.value)


def test_committed_env_file_is_rejected_before_read(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("GH_TOKEN=" + TOKEN)
    monkeypatch.setattr(credentials.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, ".env", ""))
    with pytest.raises(credentials.CredentialError, match="env-file-must-not-be-tracked"):
        credentials.load_dispatch_env(path, environ={})


def test_oversize_env_file_is_rejected_before_subprocess_or_read(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"x" * (credentials.MAX_ENV_BYTES + 1))
    with pytest.raises(credentials.CredentialError, match="bounded-ordinary-env-file-required"):
        credentials.load_dispatch_env(path, environ={})


def test_dispatch_loads_only_explicit_env_before_download(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(credentials.subprocess, "run", untracked)
    path = tmp_path / ".env"
    path.write_text("GH_TOKEN=" + TOKEN)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    seen = []
    monkeypatch.setattr(dispatch, "download_input",
                        lambda *a, **k: seen.append(os.environ.get("GH_TOKEN")) or {"downloaded": False})
    assert dispatch.main(["--request", "request.json", "--download-input"]) == 0
    assert seen == [None], "No implicit .env discovery"
    assert dispatch.main(["--request", "request.json", "--download-input", "--env-file", str(path)]) == 0
    assert seen == [None, TOKEN]
    assert TOKEN not in str(capsys.readouterr())


def test_pipeline_job_cannot_load_a_local_env_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    path.write_text("GH_TOKEN=" + TOKEN)
    assert dispatch.main(["--request", "request.json", "--job-provider", "gha",
                          "--download-input", "--env-file", str(path)]) == 2
    assert "local-dispatch-env-file-only" in capsys.readouterr().err


@pytest.mark.parametrize("name", [".env", ".env.local", "configs/private.env", ".env/variables.json"])
def test_env_file_cannot_be_a_pipeline_request(name, capsys):
    assert dispatch.main(["--request", name, "--download-input"]) == 2
    assert "environment-file-transport-forbidden" in capsys.readouterr().err
