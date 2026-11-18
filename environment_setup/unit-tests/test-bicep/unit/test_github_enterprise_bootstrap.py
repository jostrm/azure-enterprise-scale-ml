"""A consumer repository on GitHub Enterprise (GHE.com or GHES) gets through the bootstrap; github.com is unchanged.

github_repository = [HOST/]OWNER/REPO (decided 2026-11-18). Offline: gh, Entra and GitHub are fakes.
"""

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap" / "lib"
SCALESET = LIB / "create-new-aifactory-scaleset.sh"
GHE = "https://contoso.ghe.com/research/aifactory"
GHES = "https://git.contoso.com/platform/aifactory"
DOTCOM = "https://github.com/contoso/aifactory"
CLIENT = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _load(name):
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    spec = importlib.util.spec_from_file_location(name, LIB / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


en = _load("factory_enrollment")
fl = _load("factory_lifecycle")


class GhRecorder:
    def __init__(self, body=b"{}"):
        self.calls, self.body = [], body

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout=b"HTTP/2.0 200 OK\r\n\r\n" + self.body, stderr=b"")


# --- factory_enrollment ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("repository, host", [(DOTCOM, "github.com"), (GHE, "contoso.ghe.com"), (GHES, "git.contoso.com")])
def test_enrollment_gh_targets_the_route_host(repository, host):
    runner = GhRecorder()
    cloud = en.Cloud({"route": {"kind": "gha", "repository": repository}}, command_runner=runner)
    cloud.gh("GET", "repos/x/y")
    assert runner.calls == [["gh", "api", "--hostname", host, "--include", "--method", "GET", "repos/x/y"]]


def test_enrollment_gh_without_route_stays_github_com_and_honours_an_explicit_host():
    runner = GhRecorder()
    cloud = en.Cloud({}, command_runner=runner)
    cloud.gh("GET", "repos/x/y")
    cloud.github_host = "contoso.ghe.com"
    cloud.gh("GET", "repos/x/y")
    assert [call[3] for call in runner.calls] == ["github.com", "contoso.ghe.com"]


@pytest.mark.parametrize("repository", [DOTCOM, GHE, GHES])
def test_enrollment_accepts_github_enterprise_route_urls(repository):
    assert en.safe_route_repository("gha", repository)


@pytest.mark.parametrize("repository", [
    "https://gitlab.com/contoso/aifactory", "https://github.com:8443/contoso/aifactory", "http://github.com/a/b",
    "https://www.github.com/contoso/aifactory", "https://contoso.ghe.com/research/..", "https://github.com/a/b/c"])
def test_enrollment_still_rejects_unsafe_route_urls(repository):
    assert not en.safe_route_repository("gha", repository)


def test_subject_prefix_compares_the_owner_repo_path_of_an_enterprise_slug():
    repo = {"full_name": "research/aifactory"}
    assert en.github_subject_prefix("contoso.ghe.com/research/aifactory", repo, {"use_default": True}) \
        == "repo:research/aifactory"
    assert en.github_subject_prefix("contoso/aifactory", {"full_name": "contoso/aifactory"}, {"use_default": True}) \
        == "repo:contoso/aifactory"
    with pytest.raises(en.EnrollmentError):
        en.github_subject_prefix("contoso.ghe.com/research/other", repo, {"use_default": True})


@pytest.mark.parametrize("repository, issuer", [
    (DOTCOM, "https://token.actions.githubusercontent.com"), (GHE, "https://token.actions.contoso.ghe.com"),
    (GHES, "https://git.contoso.com/_services/token")])
def test_enrollment_provider_federates_with_the_host_issuer(monkeypatch, repository, issuer):
    calls = []

    class FakeCloud:
        def gh(self, method, endpoint, body=None, allowed=(200,)):
            calls.append(endpoint)
            if endpoint.count("/") == 2:
                return 200, {}, {"full_name": endpoint.removeprefix("repos/")}
            if endpoint.endswith("/customization/sub"):
                return 200, {}, {"use_default": True}
            return 404, {}, None

    monkeypatch.setattr(en, "_github_environment_map", lambda route, target, saved: {})
    request = {"route": {"kind": "gha", "repository": repository, "auth_namespace": "aif-dev"},
               "target": {"tenant_id": "t", "subscription_id": "s"}}
    provider = en._provider(FakeCloud(), request, None)
    path = repository.split("/", 3)[3]
    assert provider["issuer"] == issuer
    assert provider["subject"] == "repo:" + path + ":environment:aif-dev"
    assert calls[0] == "repos/" + path


# --- factory_lifecycle ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("repository", [DOTCOM, GHE, GHES])
def test_lifecycle_manifest_accepts_github_enterprise_routes(repository):
    assert fl.supported_route_repository("gha", repository)


def test_lifecycle_manifest_rejects_unsafe_routes():
    for value in ("https://gitlab.com/a/b", "https://GitHub.com/a/b", "https://github.com:443/a/b",
                  "https://contoso.ghe.com/a/b/c"):
        assert not fl.supported_route_repository("gha", value)
    assert fl.supported_route_repository("ado", "https://dev.azure.com/contoso/project/_git/aifactory")


def _jwt(claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "e30." + body + ".sig"


def _workload_cloud(monkeypatch, repository, request_url):
    document = {"route": {"repository": repository, "commit": "a" * 40, "auth_namespace": "aif-dev"},
                "run_id": "run-1", "target": {"tenant_id": "t"}}
    cloud = fl.Cloud(document, command_runner=lambda *a, **k: None, opener=object(), expected_object_id=CLIENT)
    cloud.workload_client_id = CLIENT
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL", request_url)
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "request-token")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    return cloud


@pytest.mark.parametrize("repository, request_url, issuer", [
    (DOTCOM, "https://pipelinesghubeus6.actions.githubusercontent.com/abc/idtoken?api-version=2.0",
     "https://token.actions.githubusercontent.com"),
    (GHE, "https://pipelines.actions.contoso.ghe.com/abc/idtoken?api-version=2.0",
     "https://token.actions.contoso.ghe.com"),
    (GHES, "https://git.contoso.com/_services/pipelines/abc/idtoken?api-version=2.0",
     "https://git.contoso.com/_services/token"),
])
def test_lifecycle_workload_token_trusts_only_the_route_host_issuer(monkeypatch, repository, request_url, issuer):
    cloud = _workload_cloud(monkeypatch, repository, request_url)
    path = repository.split("/", 3)[3]
    claims = {"iss": issuer, "aud": "api://AzureADTokenExchange", "repository": path, "sha": "a" * 40,
              "ref": "refs/tags/aifactory-runs/run-1", "environment": "aif-dev", "sub": "repo:" + path,
              "run_id": "42"}
    responses = iter([{"value": _jwt(claims)}, {"access_token": "arm"}])
    monkeypatch.setattr(cloud, "identity_json", lambda request: next(responses))
    assert cloud.github_workload_token("https://management.azure.com/") == "arm"

    # The github.com issuer is not trusted for an enterprise route, and vice versa.
    other = "https://token.actions.githubusercontent.com" if repository != DOTCOM else "https://token.actions.contoso.ghe.com"
    responses = iter([{"value": _jwt({**claims, "iss": other})}])
    monkeypatch.setattr(cloud, "identity_json", lambda request: next(responses))
    with pytest.raises(fl.Blocked):
        cloud.github_workload_token("https://management.azure.com/")


def test_lifecycle_workload_token_rejects_a_foreign_token_request_host(monkeypatch):
    cloud = _workload_cloud(monkeypatch, GHE, "https://x.actions.githubusercontent.com/idtoken")
    with pytest.raises(fl.Blocked):
        cloud.github_workload_token("https://management.azure.com/")


class Stop(Exception):
    pass


def _state_cloud(monkeypatch, repository, sent):
    document = {"route": {"repository": repository}, "coordination_mode": "single-writer", "locks": {}}
    monkeypatch.setattr(fl, "single_writer", lambda document: True)

    def opener_open(request, timeout=None):
        sent.append((request.full_url, request.headers.get("Authorization")))
        raise Stop()

    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return fl.Cloud(document, command_runner=lambda *a, **k: None, opener=SimpleNamespace(open=opener_open),
                    expected_object_id=CLIENT)


@pytest.mark.parametrize("repository, url, variable", [
    (DOTCOM, "https://api.github.com/repos/contoso/aifactory", "GH_TOKEN"),
    (GHE, "https://api.contoso.ghe.com/repos/research/aifactory", "GH_TOKEN"),
    (GHES, "https://git.contoso.com/api/v3/repos/platform/aifactory", "GH_ENTERPRISE_TOKEN"),
])
def test_lifecycle_state_request_uses_the_host_api_and_token(monkeypatch, repository, url, variable):
    sent = []
    cloud = _state_cloud(monkeypatch, repository, sent)
    monkeypatch.setenv(variable, "host-token")
    if variable != "GH_TOKEN":
        monkeypatch.setenv("GH_TOKEN", "github-com-token")
    with pytest.raises(Stop):
        cloud.state_request("gha", "GET", "repos/" + url.split("/repos/")[1], None, (200,))
    assert sent == [(url, "Bearer host-token")]


def test_lifecycle_state_request_never_sends_a_github_com_token_to_enterprise_server(monkeypatch):
    sent = []
    cloud = _state_cloud(monkeypatch, GHES, sent)
    monkeypatch.setenv("GH_TOKEN", "github-com-token")
    with pytest.raises(fl.Blocked):
        cloud.state_request("gha", "GET", "repos/platform/aifactory", None, (200,))
    assert sent == []


def test_lifecycle_interactive_state_token_comes_from_gh_for_the_route_host(monkeypatch):
    sent, commands = [], []
    cloud = _state_cloud(monkeypatch, GHE, sent)
    cloud.pipeline_identity = False
    cloud.command = lambda argv, **kwargs: commands.append(argv) or ""
    with pytest.raises(fl.Blocked):
        cloud.state_request("gha", "GET", "repos/research/aifactory", None, (200,))
    assert commands == [["gh", "auth", "token", "--hostname", "contoso.ghe.com"]]


def test_lifecycle_scoped_and_run_checks_name_the_route_host():
    source = (LIB / "factory_lifecycle.py").read_text(encoding="utf-8")
    assert '"--hostname", "github.com"' not in source
    assert '"github.com/" + repository' not in source
    assert "https://api.github.com/" not in source
    assert '"https://token.actions.githubusercontent.com"' not in source


# --- registered bootstrap, runner, environments ---------------------------------------------------------------------

def test_registered_repository_url_and_api_calls_use_the_slug_host():
    rr = _load("registered_repository")
    assert rr.repository_url("gha", {"github_repository": "contoso/aifactory"}) == DOTCOM
    assert rr.repository_url("gha", {"github_repository": "contoso.ghe.com/research/aifactory"}) == GHE
    with pytest.raises(rr.enrollment.EnrollmentError):      # registered_repository's own factory_enrollment import
        rr.repository_url("gha", {"github_repository": "gitlab.com/contoso/aifactory"})
    runner = GhRecorder(b'{"login": "research"}')
    repo = rr.Repository({"tenant_id": "t", "subscription_id": "s"}, "gha",
                         {"github_repository": "contoso.ghe.com/research/aifactory"}, command_runner=runner)
    assert repo.cloud.github_host == "contoso.ghe.com"
    repo.discover()
    assert runner.calls[-1][:4] == ["gh", "api", "--hostname", "contoso.ghe.com"]
    assert runner.calls[-1][-1] == "repos/research/aifactory"


def test_registered_repository_create_and_default_branch_target_the_host():
    rr = _load("registered_repository")
    seen = []

    def command(argv, data=None):
        seen.append(argv)
        return '{"login": "someone"}'

    runner = GhRecorder(b'{"default_branch": "main"}')
    repo = rr.Repository({"tenant_id": "t", "subscription_id": "s"}, "gha",
                         {"github_repository": "git.contoso.com/platform/aifactory"}, command_runner=runner)
    repo.cloud.command = command
    repo.create()
    repo.set_initial_default_branch()
    assert seen[0] == ["gh", "api", "--hostname", "git.contoso.com", "user"]
    assert seen[1][:4] == ["gh", "api", "--hostname", "git.contoso.com"] and "orgs/platform/repos" in seen[1]
    assert seen[2][:4] == ["gh", "api", "--hostname", "git.contoso.com"] and "repos/platform/aifactory" in seen[2]
    assert runner.calls[-1][3] == "git.contoso.com" and runner.calls[-1][-1] == "repos/platform/aifactory"


def test_github_environments_cli_targets_the_repository_host():
    ge = _load("github_environments")
    repo = ge.Repository("contoso.ghe.com/research/aifactory")
    assert repo.cloud.github_host == "contoso.ghe.com"
    assert repo.path == "research/aifactory"
    assert ge.Repository("contoso/aifactory").cloud.github_host == "github.com"
    source = (LIB / "github_environments.py").read_text(encoding="utf-8")
    assert '"--hostname", "github.com"' not in source


def test_runner_bootstrap_has_no_github_com_only_repository_rules():
    source = (LIB / "runner_bootstrap.py").read_text(encoding="utf-8")
    assert 'GH_HOST="github.com"' not in source
    assert 'removeprefix("https://github.com/")' not in source
    rb = _load("runner_bootstrap")
    assert rb.github_runner_repository(GHE) == "contoso.ghe.com/research/aifactory"
    assert rb.github_runner_repository("git@github.com:contoso/aifactory.git") == "contoso/aifactory"
    assert rb.github_runner_repository("https://gitlab.com/contoso/aifactory") is None


def test_registered_personas_reads_the_manifest_from_the_route_host():
    rp = _load("registered_personas")
    seen = []
    cloud = SimpleNamespace(command=lambda argv: seen.append(argv) or json.dumps(
        {"type": "file", "encoding": "base64", "content": base64.b64encode(b"{}").decode()}))
    for repository in (DOTCOM, GHE):
        rp.remote_manifest(cloud, {"kind": "gha", "repository": repository, "commit": "a" * 40},
                           {"persona_access_manifest": "personas/access.json"})
    assert "--hostname" not in seen[0]                      # github.com argv unchanged
    assert seen[1][seen[1].index("--hostname") + 1] == "contoso.ghe.com"


# --- create-new-aifactory-scaleset.sh -------------------------------------------------------------------------------

def test_scaleset_script_routes_every_github_host_detail_through_github_host():
    script = SCALESET.read_text(encoding="utf-8")
    assert 'AIF_REMOTE_URL="https://github.com/$GITHUB_REPOSITORY.git"' not in script
    assert '"https://github.com/$GITHUB_REPOSITORY"' not in script
    assert '--issuer "https://token.actions.githubusercontent.com"' not in script
    assert 'gh api "repos/$GITHUB_REPOSITORY' not in script
    assert 'gh api --method POST "repos/$GITHUB_REPOSITORY' not in script
    assert 'gh api --paginate "repos/$GITHUB_REPOSITORY' not in script
    assert "github_host.py" in script
    assert '--issuer "$AIF_GITHUB_OIDC_ISSUER"' in script


def _bash():
    candidates = ([r"C:\Program Files\Git\bin\bash.exe"] if os.name == "nt" else []) + [shutil.which("bash")]
    found = [candidate for candidate in candidates if candidate and Path(candidate).is_file()]
    assert found, "bash is required for the scale-set script probe"
    return found[0]


def _fields(value):
    script = SCALESET.read_text(encoding="utf-8")
    start = script.index("aif_github_repository_fields() {")
    end = script.index("\n}\n", start) + 3
    probe = (script[start:end] + '\nAIF_PYTHON=("$1")\nAIF_SCALESET_LIB_DIR="$2"\nGITHUB_REPOSITORY="$3"\n'
             'aif_github_repository_fields || exit 9\n'
             'printf "%s|%s|%s|%s|%s\\n" "$AIF_GITHUB_HOST" "$AIF_GITHUB_PATH" "$GITHUB_REPOSITORY" '
             '"$AIF_GITHUB_URL" "$AIF_GITHUB_OIDC_ISSUER"\n')
    return subprocess.run([_bash(), "-c", probe, "probe", sys.executable.replace("\\", "/"),
                           str(LIB).replace("\\", "/"), value], capture_output=True, text=True)


def test_scaleset_github_fields_function_exports_host_details():
    for value, expected in [
        ("contoso/aifactory", "github.com|contoso/aifactory|contoso/aifactory|https://github.com/contoso/aifactory|"
                              "https://token.actions.githubusercontent.com"),
        ("https://contoso.ghe.com/research/aifactory.git",
         "contoso.ghe.com|research/aifactory|contoso.ghe.com/research/aifactory|"
         "https://contoso.ghe.com/research/aifactory|https://token.actions.contoso.ghe.com"),
    ]:
        result = _fields(value)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().replace("\r", "") == expected
    assert _fields("gitlab.com/a/b").returncode == 9
