"""GitHub Enterprise consumer repositories reach every pipeline bootstrap module (contract 2026-11-18).
# release/v1.25 subset: the pipeline_* modules exist on main only; their cases live in main's copy.

``github_repository`` = ``[HOST/]OWNER/REPO``: a GHE.com (contoso.ghe.com) or GitHub Enterprise Server
(git.contoso.com) consumer gets its own REST API, ``gh --hostname``, OIDC issuer and token variable, and a
github.com token is never sent to it. Plain github.com inputs give exactly today's URLs, argv and tokens.
Offline: every provider call is intercepted.
"""

import base64
import copy
import importlib
import importlib.util
import json
import sys
import time
import types
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap" / "lib"
sys.path.insert(0, str(LIB))

DOTCOM = "https://github.com/acme/factory"
GHE_CLOUD = "https://contoso.ghe.com/research/aifactory"
GHES = "https://git.contoso.com/platform/aifactory"
COMMIT = "b" * 40

github_host = importlib.import_module("github_host")


def load(name):
    spec = importlib.util.spec_from_file_location("ghe_test_" + name, LIB / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Live network is forbidden"))
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GITHUB_SERVER_URL"):
        monkeypatch.delenv(name, raising=False)


class Response:
    def __init__(self, body, status=200):
        self.status, self.code = status, status
        self.headers = {}
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self, limit=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Opener:
    """Records every request; answers with queued values (an exception is raised)."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def open(self, request, timeout=None):
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else {}
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, Response) else Response(answer)


class _Passed(Exception):
    pass


# --- factory_deletion_pipeline -------------------------------------------------------------------------------------

def deletion_module():
    module = load("factory_deletion_pipeline")

    class Blocked(Exception):
        pass

    def require(condition, code):
        if not condition:
            raise Blocked(code)
    module.fl = types.SimpleNamespace(require=require, Blocked=Blocked)
    return module


@pytest.mark.parametrize("repository,hostname,path", [
    (DOTCOM, "github.com", "acme/factory"), (GHES, "git.contoso.com", "platform/aifactory"),
    (GHE_CLOUD, "contoso.ghe.com", "research/aifactory"),
])
def test_factory_delete_resume_reads_the_run_on_the_routes_host(repository, hostname, path):
    module = deletion_module()
    document = {"run_id": "run-1", "route": {"kind": "gha", "repository": repository, "commit": COMMIT}}
    calls = []

    def command(argv):
        calls.append(argv)
        return json.dumps({"id": 5, "head_sha": COMMIT, "display_title": "factory-lifecycle [run-1]",
                           "status": "completed", "conclusion": "success"})
    receipt = {"remote_run": {"kind": "gha", "run_id": 5}}
    locks = types.SimpleNamespace(assert_held=lambda: None)
    assert module.resume_dispatch(types.SimpleNamespace(command=command), locks, document, receipt, Mock(),
                                  lambda _: None) is True
    assert calls == [["gh", "api", "--method", "GET", f"repos/{path}/actions/runs/5", "--hostname", hostname]]


@pytest.mark.parametrize("repository,repo_argument,hostname", [
    (DOTCOM, "github.com/acme/factory", "github.com"),
    (GHES, "git.contoso.com/platform/aifactory", "git.contoso.com"),
])
def test_factory_delete_cleanup_uses_the_routes_host_for_secrets_and_tags(repository, repo_argument, hostname):
    module = deletion_module()
    run_id = "12345678-1234-1234-1234-123456789abc"
    prefix = "AIF_LIFECYCLE_" + run_id.replace("-", "").upper()
    ref = "refs/tags/aifactory-runs/" + run_id
    path = urlsplit(repository).path.strip("/")
    document = {"run_id": run_id, "route": {"kind": "gha", "repository": repository, "commit": COMMIT,
                                            "auth_namespace": "factory-stage"}}
    receipt = {"remote_terminal": True, "remote_artifacts": {"ref": ref, "secret_prefix": prefix,
                                                            "auth_namespace": "factory-stage", "chunks": 1}}
    calls = []

    def command(argv):
        calls.append(argv)
        if argv[:3] == ["gh", "secret", "list"]:
            return json.dumps([{"name": prefix + "_0"}])
        if "matching-refs" in " ".join(argv):
            return json.dumps([{"ref": ref, "object": {"sha": COMMIT}}])
        return ""
    module.cleanup_resumed_artifacts(types.SimpleNamespace(command=command), document, receipt, Mock())
    assert calls == [
        ["gh", "secret", "list", "--repo", repo_argument, "--env", "factory-stage", "--json", "name"],
        ["gh", "secret", "delete", prefix + "_0", "--repo", repo_argument, "--env", "factory-stage"],
        ["gh", "api", "--method", "GET", "repos/" + path + "/git/matching-refs/" + ref.removeprefix("refs/"),
         "--hostname", hostname],
        ["gh", "api", "--method", "DELETE", "repos/" + path + "/git/" + ref, "--hostname", hostname],
    ]


# --- hub_private_transition ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("repository,path", [(DOTCOM, "acme/factory"), (DOTCOM + ".git", "acme/factory"),
                                             (GHES, "platform/aifactory"), (GHE_CLOUD, "research/aifactory")])
def test_hub_writer_attestation_reads_the_enterprise_repository(repository, path):
    module = importlib.import_module("hub_private_transition")
    paths = []

    def provider_read(writer, value):
        paths.append(value)
        if len(paths) == 1:
            return {"id": 1, "full_name": path}
        raise _Passed()
    writer = {"provider": "gha", "repository": repository, "repository_id": 1, "runner_id": 3}
    with pytest.raises(_Passed):
        module.Cloud.attest_writer(types.SimpleNamespace(provider_read=provider_read), writer, "a" * 64)
    assert paths[:2] == ["repos/" + path, "repos/" + path + "/actions/runners/3"]


@pytest.mark.parametrize("repository", ["https://gitlab.com/acme/factory", "acme/factory", "https://github.com/acme"])
def test_hub_writer_attestation_still_requires_a_github_url(repository):
    module = importlib.import_module("hub_private_transition")
    with pytest.raises(module.TransitionError, match="github-repository-required"):
        module.Cloud.attest_writer(types.SimpleNamespace(provider_read=Mock()), {"provider": "gha",
                                                                                  "repository": repository}, "a" * 64)


@pytest.mark.parametrize("left,right,same", [
    ("https://github.com/Acme/Factory", "acme/factory", True),
    ("https://github.com/acme/factory.git", "https://github.com/acme/factory/", True),
    (GHES, "git.contoso.com/Platform/AIFactory", True),
    (GHES, "platform/aifactory", False),
    (GHE_CLOUD, "https://github.com/research/aifactory", False),
    ("https://dev.azure.com/acme/project/_git/factory", "https://dev.azure.com/Acme/Project/_git/Factory.git", True),
])
def test_hub_writer_selection_compares_host_and_repository(left, right, same):
    module = importlib.import_module("hub_private_transition")
    assert (module._repository_key(left) == module._repository_key(right)) is same


# --- project_deployment --------------------------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path, monkeypatch):
    from .test_project_deployment_contract import pd, instance, document, SUBS, TENANT
    monkeypatch.setattr(pd.subprocess, "run", Mock(side_effect=AssertionError("No real command is permitted")))

    def prepare(origin, configured):
        deployment = instance("gha")
        deployment.root = tmp_path
        (tmp_path / ".git").mkdir(exist_ok=True)
        (tmp_path / "aifactory").mkdir(exist_ok=True)
        for relative in pd.FILES["gha"]:
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# " + pd.CONTRACT, encoding="utf-8")
        data = document()
        for section in data.values():
            section["GITHUB_NEW_REPO"] = configured
        config = tmp_path / "aifactory" / "selected.json"
        config.write_text(json.dumps(data), encoding="utf-8")
        deployment.command = Mock(side_effect=lambda argv, **kwargs: origin if argv[0] == "git" else 0)
        deployment.read_json = Mock(side_effect=lambda argv: {"id": 17} if argv[:2] == ["gh", "api"] else {
            "id": SUBS["stage"], "tenantId": TENANT, "user": {"name": "synthetic-test-owner"}})
        deployment.prepare("017", "stage", str(config))
        return deployment
    return pd, prepare


@pytest.mark.parametrize("origin,configured,repository,user", [
    ("https://github.com/org/consumer.git", "org/consumer", "org/consumer", ["gh", "api", "user"]),
    ("git@github.com:org/consumer.git", "https://github.com/org/consumer", "org/consumer", ["gh", "api", "user"]),
    ("https://git.contoso.com/platform/aifactory.git", "git.contoso.com/platform/aifactory",
     "git.contoso.com/platform/aifactory", ["gh", "api", "user", "--hostname", "git.contoso.com"]),
    ("git@contoso.ghe.com:research/aifactory.git", "https://contoso.ghe.com/research/aifactory",
     "contoso.ghe.com/research/aifactory", ["gh", "api", "user", "--hostname", "contoso.ghe.com"]),
])
def test_project_deployment_targets_the_consumers_host(project, origin, configured, repository, user):
    pd, prepare = project
    deployment = prepare(origin, configured)
    assert deployment.repository == repository
    assert deployment.github_user_command() == user
    assert user in [call.args[0] for call in deployment.read_json.call_args_list]


@pytest.mark.parametrize("origin,configured", [
    ("https://git.contoso.com/platform/aifactory.git", "platform/aifactory"),
    ("https://github.com/org/consumer.git", "git.contoso.com/org/consumer"),
    ("https://token@github.com/org/consumer.git", "org/consumer"),
])
def test_project_deployment_rejects_a_different_host_or_credentialed_origin(project, origin, configured):
    _, prepare = project
    with pytest.raises(ValueError, match="GitHub"):
        prepare(origin, configured)
