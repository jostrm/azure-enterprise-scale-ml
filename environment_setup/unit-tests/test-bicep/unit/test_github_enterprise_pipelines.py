"""GitHub Enterprise consumer repositories reach every pipeline bootstrap module (contract 2026-11-18).

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

dispatch = importlib.import_module("pipeline_dispatch")
approvals = importlib.import_module("pipeline_approvals")
credentials = importlib.import_module("pipeline_credentials")
lifecycle = importlib.import_module("pipeline_lifecycle")
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


# --- pipeline_dispatch ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("repository,base", [
    (DOTCOM, "https://api.github.com/repos/acme/factory"),
    (GHE_CLOUD, "https://api.contoso.ghe.com/repos/research/aifactory"),
    (GHES, "https://git.contoso.com/api/v3/repos/platform/aifactory"),
])
def test_dispatch_binding_targets_the_repository_hosts_rest_api(repository, base):
    binding = {"schema": 1, "provider": "gha", "repository": repository, "consumer_commit": COMMIT}
    assert dispatch.validate_binding({"provider": "gha"}, binding) == base


@pytest.mark.parametrize("repository", [
    "https://gitlab.com/acme/factory", "https://api.github.com/acme/factory", "https://GitHub.com/acme/factory",
    "https://github.com/acme", "http://git.contoso.com/platform/aifactory", "https://github.com/acme/..",
])
def test_dispatch_binding_still_rejects_non_github_repositories(repository):
    binding = {"schema": 1, "provider": "gha", "repository": repository, "consumer_commit": COMMIT}
    with pytest.raises(dispatch.DispatchError, match="repository-invalid"):
        dispatch.validate_binding({"provider": "gha"}, binding)


@pytest.mark.parametrize("base,token", [
    ("https://api.github.com/repos/acme/factory", "dotcom-token"),
    ("https://api.contoso.ghe.com/repos/research/aifactory", "dotcom-token"),
    ("https://git.contoso.com/api/v3/repos/platform/aifactory", "enterprise-token"),
])
def test_dispatch_transport_sends_only_the_hosts_token(base, token, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "dotcom-token")
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "enterprise-token")
    opener = Opener({"ok": True})
    dispatch.ProviderTransport("gha", base, opener=opener).request("GET", base + "/actions/runs/1")
    assert opener.requests[0].full_url == base + "/actions/runs/1"
    assert opener.requests[0].get_header("Authorization") == "Bearer " + token


def test_enterprise_server_transport_never_falls_back_to_a_github_com_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "dotcom-token")
    base = "https://git.contoso.com/api/v3/repos/platform/aifactory"
    opener = Opener()
    with pytest.raises(dispatch.DispatchError, match="GH_ENTERPRISE_TOKEN-or-GITHUB_ENTERPRISE_TOKEN-required"):
        dispatch.ProviderTransport("gha", base, opener=opener).request("GET", base)
    assert opener.requests == []
    monkeypatch.delenv("GH_TOKEN")
    with pytest.raises(dispatch.DispatchError, match="^GH_TOKEN-or-GITHUB_TOKEN-required$"):
        dispatch.ProviderTransport("gha", "https://api.github.com/repos/acme/factory", opener=opener).request(
            "GET", "https://api.github.com/repos/acme/factory")


@pytest.mark.parametrize("base,target,allowed", [
    ("https://git.contoso.com/api/v3/repos/platform/aifactory", "https://git.contoso.com/storage/a.zip", True),
    ("https://api.contoso.ghe.com/repos/research/aifactory", "https://results.contoso.ghe.com/a.zip", True),
    ("https://api.github.com/repos/acme/factory", "https://git.contoso.com/storage/a.zip", False),
    ("https://git.contoso.com/api/v3/repos/platform/aifactory", "https://git.fabrikam.com/a.zip", False),
    ("https://api.github.com/repos/acme/factory", "https://x.blob.core.windows.net/a.zip", True),
])
def test_artifact_redirects_stay_on_the_providers_hosts(base, target, allowed, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "dotcom-token")
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "enterprise-token")
    redirect = HTTPError(base + "/actions/artifacts/1/zip", 302, "Found", {"Location": target}, None)
    opener = Opener(redirect, Response(b"zip-bytes"))
    transport = dispatch.ProviderTransport("gha", base, opener=opener)
    if allowed:
        assert transport.request("GET", base + "/actions/artifacts/1/zip", raw=True)[2] == b"zip-bytes"
        assert opener.requests[1].full_url == target and not opener.requests[1].get_header("Authorization")
    else:
        with pytest.raises(dispatch.DispatchError, match="artifact-redirect-outside-provider"):
            transport.request("GET", base + "/actions/artifacts/1/zip", raw=True)


@pytest.mark.parametrize("repository,url", [
    (DOTCOM, "https://api.github.com/repos/acme/factory/git/ref/heads/x"),
    (GHE_CLOUD, "https://api.contoso.ghe.com/repos/research/aifactory/git/ref/heads/x"),
    (GHES, "https://git.contoso.com/api/v3/repos/platform/aifactory/git/ref/heads/x"),
])
def test_receipt_reader_reads_provider_state_from_the_hosts_api(repository, url):
    path = urlsplit(repository).path.strip("/")
    calls = []

    class Transport:
        def request(self, method, target, body=None, raw=False):
            calls.append(target)
            return 200, {}, {}

    reader = dispatch.ProviderReceiptReader({"provider": "gha", "repository": repository, "consumer_commit": COMMIT},
                                            transport=Transport())
    reader.state_request("gha", "GET", "repos/" + path + "/git/ref/heads/x")
    assert calls == [url]


@pytest.mark.parametrize("repository,full_name", [(DOTCOM, "acme/factory"), (GHES, "platform/aifactory"),
                                                 (GHE_CLOUD, "Research/AIFactory")])
def test_run_identity_compares_the_enterprise_full_name(repository, full_name):
    run = {"id": 7, "workflow_id": 9, "event": "workflow_dispatch", "display_title": "pipelines-only [c]",
           "head_sha": COMMIT, "run_attempt": 1, "repository": {"full_name": full_name}}
    binding = {"repository": repository, "consumer_commit": COMMIT}
    dispatch._gha_identity(run, binding=binding, workflow=9, correlation="c")
    with pytest.raises(dispatch.DispatchError, match="provider-run-identity-mismatch"):
        dispatch._gha_identity({**run, "repository": {"full_name": "other/factory"}}, binding=binding,
                               workflow=9, correlation="c")


@pytest.mark.parametrize("remote,origin", [
    ("git@github.com:acme/factory.git", "https://github.com/acme/factory"),
    ("https://github.com/acme/factory.git", "https://github.com/acme/factory"),
    ("git@git.contoso.com:platform/aifactory.git", "https://git.contoso.com/platform/aifactory"),
    ("git@contoso.ghe.com:research/aifactory", "https://contoso.ghe.com/research/aifactory"),
    ("git@ssh.dev.azure.com:v3/acme/project/factory", "https://dev.azure.com/acme/project/_git/factory"),
])
def test_ssh_origins_map_to_their_hosts_https_url(remote, origin, monkeypatch):
    monkeypatch.setattr(dispatch, "_git", lambda root, *args: remote)
    assert dispatch._origin_repository(Path(".")) == origin


@pytest.mark.parametrize("environment,repository", [
    ({"GITHUB_REPOSITORY": "acme/factory"}, "https://github.com/acme/factory"),
    ({"GITHUB_REPOSITORY": "acme/factory", "GITHUB_SERVER_URL": "https://github.com"}, "https://github.com/acme/factory"),
    ({"GITHUB_REPOSITORY": "platform/aifactory", "GITHUB_SERVER_URL": "https://git.contoso.com"}, GHES),
    ({"GITHUB_REPOSITORY": "research/aifactory", "GITHUB_SERVER_URL": "https://contoso.ghe.com/"}, GHE_CLOUD),
])
def test_actions_job_repository_uses_the_servers_host(environment, repository):
    assert dispatch._actions_repository(environment) == repository


# --- pipeline_approvals --------------------------------------------------------------------------------------------

def oidc_environment(url):
    return {"ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token", "ACTIONS_ID_TOKEN_REQUEST_URL": url}


@pytest.mark.parametrize("host,url", [
    ("github.com", "https://pipelinesghubeus2.actions.githubusercontent.com/x/_apis/distributedtask/hubs/build/plans/p"),
    ("contoso.ghe.com", "https://pipelines.actions.contoso.ghe.com/x/_apis/distributedtask/hubs/build/plans/p"),
    ("git.contoso.com", "https://git.contoso.com/_services/pipelines/_apis/distributedtask/hubs/build/plans/p"),
])
def test_oidc_token_request_is_accepted_only_on_the_hosts_actions_service(host, url):
    opener = Opener({"value": "signed-jwt"})
    oidc = approvals.GitHubOIDC(oidc_environment(url), opener=opener) if host == "github.com" else \
        approvals.GitHubOIDC(oidc_environment(url), opener=opener, host=host)
    assert oidc.token("api://audience") == "signed-jwt"
    assert urlsplit(opener.requests[0].full_url).hostname == urlsplit(url).hostname
    if host != "github.com":
        with pytest.raises(approvals.ApprovalError, match="authenticated-github-oidc-endpoint-required"):
            approvals.GitHubOIDC(oidc_environment(url), opener=Opener()).token("api://audience")


@pytest.mark.parametrize("host,jwks", [
    (None, approvals.JWKS_URL),
    ("github.com", "https://token.actions.githubusercontent.com/.well-known/jwks"),
    ("contoso.ghe.com", "https://token.actions.contoso.ghe.com/.well-known/jwks"),
    ("git.contoso.com", "https://git.contoso.com/_services/token/.well-known/jwks"),
])
def test_oidc_signing_keys_come_from_the_hosts_issuer(host, jwks):
    opener = Opener({"keys": []})
    oidc = approvals.GitHubOIDC({}, opener=opener) if host is None else approvals.GitHubOIDC({}, opener=opener, host=host)
    oidc.jwks()
    assert opener.requests[0].full_url == jwks


def signed(claims):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def encode(value):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    head = encode({"alg": "RS256", "typ": "JWT", "kid": "k"}) + "." + encode(claims)
    signature = key.sign(head.encode(), padding.PKCS1v15(), hashes.SHA256())
    numbers = key.public_key().public_numbers()
    jwks = {"keys": [{"kid": "k", "kty": "RSA", "n": encode(numbers.n.to_bytes(256, "big")),
                      "e": encode(numbers.e.to_bytes(3, "big"))}]}
    return head + "." + encode(signature), jwks


def test_signed_job_token_must_carry_the_hosts_issuer():
    now = int(time.time())
    issuer = "https://git.contoso.com/_services/token"
    token, jwks = signed({"iss": issuer, "aud": "api://a", "iat": now, "nbf": now, "exp": now + 300})
    assert approvals.verify_github_jwt(token, jwks, "api://a", issuer=issuer)["iss"] == issuer
    with pytest.raises(approvals.ApprovalError, match="provider-oidc-time-or-audience-invalid"):
        approvals.verify_github_jwt(token, jwks, "api://a")
    dotcom, keys = signed({"iss": approvals.ISSUER, "aud": "api://a", "iat": now, "nbf": now, "exp": now + 300})
    assert approvals.verify_github_jwt(dotcom, keys, "api://a")["iss"] == approvals.ISSUER


def review_record(repository, path):
    return {"operation_id": "11111111-1111-4111-8111-111111111111", "plan_hash": "d" * 64,
            "prepared_at": "2026-11-18T10:00:00Z", "snapshot": {"binding": {"repository": repository}},
            "plan": {"origin": {"provider": "gha", "repository": path, "run_id": "42", "attempt": 1,
                                "commit": COMMIT, "ref": "refs/heads/main"}}}


@pytest.mark.parametrize("repository,path,base,host", [
    (DOTCOM, "acme/factory", "https://api.github.com/repos/acme/factory", "github.com"),
    (GHE_CLOUD, "research/aifactory", "https://api.contoso.ghe.com/repos/research/aifactory", "contoso.ghe.com"),
    (GHES, "platform/aifactory", "https://git.contoso.com/api/v3/repos/platform/aifactory", "git.contoso.com"),
])
def test_native_review_reads_the_bound_hosts_api_and_issuer(repository, path, base, host):
    review = approvals._Review(review_record(repository, path), None, None, {}, time.time)
    assert review.base == base and review.transport.base == base
    assert review.oidc.jwks_url == github_host.oidc_issuer_for(host) + "/.well-known/jwks"
    assert review.issuer == github_host.oidc_issuer_for(host)


def test_native_review_without_a_bound_url_uses_the_jobs_server():
    record = review_record(None, "platform/aifactory")
    record["snapshot"] = {}
    review = approvals._Review(record, None, None, {"GITHUB_SERVER_URL": "https://git.contoso.com"}, time.time)
    assert review.base == "https://git.contoso.com/api/v3/repos/platform/aifactory"
    assert approvals._Review(record, None, None, {}, time.time).base == "https://api.github.com/repos/platform/aifactory"


# --- pipeline_lifecycle_cloud --------------------------------------------------------------------------------------

def lifecycle_transport(repository, environ):
    module = importlib.import_module("pipeline_lifecycle_cloud")
    transport = object.__new__(module._ProviderTransport)
    transport._provider_route = {"kind": "gha", "repository": repository}
    transport._provider_environ = environ
    transport.opener = Opener({"ok": True})
    return transport


@pytest.mark.parametrize("repository,url,token", [
    (DOTCOM, "https://api.github.com/repos/acme/factory/actions/runs", "dotcom-token"),
    (GHE_CLOUD, "https://api.contoso.ghe.com/repos/research/aifactory/actions/runs", "dotcom-token"),
    (GHES, "https://git.contoso.com/api/v3/repos/platform/aifactory/actions/runs", "enterprise-token"),
])
def test_lifecycle_state_transport_targets_the_hosts_api_with_its_token(repository, url, token):
    transport = lifecycle_transport(repository, {"GH_TOKEN": "dotcom-token", "GH_ENTERPRISE_TOKEN": "enterprise-token"})
    path = urlsplit(repository).path.strip("/")
    transport._provider_request("gha", "GET", "repos/" + path + "/actions/runs", None, (200,), limit=4096)
    assert transport.opener.requests[0].full_url == url
    assert transport.opener.requests[0].get_header("Authorization") == "Bearer " + token
    with pytest.raises(lifecycle.PipelineError, match="provider-repository-scope-mismatch"):
        transport._provider_request("gha", "GET", "repos/other/factory/actions/runs", None, (200,), limit=4096)


def test_lifecycle_state_transport_never_sends_a_github_com_token_to_a_server():
    transport = lifecycle_transport(GHES, {"GH_TOKEN": "dotcom-token"})
    with pytest.raises(lifecycle.PipelineError, match="pipeline-provider-token-required-or-invalid"):
        transport._provider_request("gha", "GET", "repos/platform/aifactory", None, (200,), limit=4096)
    assert transport.opener.requests == []


# --- pipeline_credentials ------------------------------------------------------------------------------------------

def test_github_com_child_environment_is_unchanged():
    environ = {"GH_TOKEN": "dotcom-token", "PATH": "/bin"}
    assert credentials.provider_environment("gha", environ=environ) == environ
    assert credentials.provider_environment("gha", environ={**environ, "GITHUB_SERVER_URL": "https://github.com"}) \
        == {**environ, "GITHUB_SERVER_URL": "https://github.com"}


def test_enterprise_server_child_gets_the_enterprise_token_variable():
    environ = {"GITHUB_SERVER_URL": "https://git.contoso.com", "GH_ENTERPRISE_TOKEN": "enterprise-token"}
    assert credentials.provider_environment("gha", environ=environ)["GH_ENTERPRISE_TOKEN"] == "enterprise-token"
    seeded = credentials.provider_environment("gha", environ={"GITHUB_SERVER_URL": "https://git.contoso.com",
                                                              "ESAF_PROVIDER_TOKEN": "seeded"})
    assert seeded["GH_ENTERPRISE_TOKEN"] == "seeded" and "GH_TOKEN" not in seeded
    with pytest.raises(credentials.CredentialError, match="provider-token-required"):
        credentials.provider_environment("gha", environ={"GITHUB_SERVER_URL": "https://git.contoso.com",
                                                         "GH_TOKEN": "dotcom-token"})
    cloud = credentials.provider_environment("gha", environ={"GITHUB_SERVER_URL": "https://contoso.ghe.com",
                                                             "GH_TOKEN": "cloud-token"})
    assert cloud["GH_TOKEN"] == "cloud-token"


def test_local_dispatch_env_file_may_hold_an_enterprise_token(tmp_path):
    assert frozenset({"GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"}) in credentials.DISPATCH_ENV_GROUPS
    assert frozenset({"GH_TOKEN", "GITHUB_TOKEN"}) in credentials.DISPATCH_ENV_GROUPS
    path = tmp_path / "dispatch.env"
    path.write_text("GH_ENTERPRISE_TOKEN=enterprise-token\nGH_TOKEN=dotcom-token\n", encoding="utf-8")
    environment = {}
    credentials.load_dispatch_env(path, environ=environment)
    assert environment == {"GH_ENTERPRISE_TOKEN": "enterprise-token", "GH_TOKEN": "dotcom-token"}


# --- pipeline_lifecycle_adapters, _bootstrap, pipeline_ancestor_runs -----------------------------------------------

@pytest.mark.parametrize("provider,netloc,allowed", [
    ("gha", "github.com", True), ("gha", "contoso.ghe.com", True), ("gha", "git.contoso.com", True),
    ("gha", "GitHub.com", False), ("gha", "api.github.com", False), ("gha", "dev.azure.com", False),
    ("gha", "github.com:443", False), ("ado", "dev.azure.com", True), ("ado", "github.com", False),
])
def test_native_binding_route_accepts_github_enterprise_hosts(provider, netloc, allowed):
    adapters = importlib.import_module("pipeline_lifecycle_adapters")
    assert adapters.provider_route_host(provider, netloc) is allowed


@pytest.mark.parametrize("repository,argv", [
    (DOTCOM, ["gh", "api", "user", "--hostname", "github.com", "--method", "GET"]),
    (GHES, ["gh", "api", "user", "--hostname", "git.contoso.com", "--method", "GET"]),
])
def test_bound_github_identity_is_read_from_the_routes_host(repository, argv):
    adapters = importlib.import_module("pipeline_lifecycle_adapters")
    assert adapters.github_user_command(repository) == argv


class _Passed(Exception):
    pass


@pytest.mark.parametrize("repository,path", [(DOTCOM, "acme/factory"), (GHES, "platform/aifactory")])
def test_bootstrap_route_matches_the_authenticated_origin_on_any_host(repository, path):
    module = importlib.import_module("pipeline_lifecycle_bootstrap")
    fake = types.SimpleNamespace(
        _inputs=lambda snapshot, operation: {"route": {"kind": "gha", "repository": repository, "ref": "refs/heads/main"}},
        review=types.SimpleNamespace(origin=lambda snapshot: {"provider": "gha", "repository": path, "run_id": "1",
                                                              "attempt": 1, "commit": COMMIT, "ref": "refs/heads/main"}),
        provider_context=None, _native_request=Mock(side_effect=_Passed))
    with pytest.raises(_Passed):
        module.BootstrapAdapter.prepare(fake, {}, "operation")
    fake.review.origin = lambda snapshot: {"provider": "gha", "repository": "other/factory", "run_id": "1",
                                           "attempt": 1, "commit": COMMIT, "ref": "refs/heads/main"}
    with pytest.raises(lifecycle.PipelineError, match="bootstrap-authenticated-route-mismatch"):
        module.BootstrapAdapter.prepare(fake, {}, "operation")


@pytest.mark.parametrize("repository,path", [(DOTCOM, "acme/factory"), (GHES, "platform/aifactory"),
                                             (GHE_CLOUD, "research/aifactory")])
def test_ancestor_repository_is_the_states_host_plus_the_origin_path(repository, path):
    module = importlib.import_module("pipeline_ancestor_runs")
    record = {"plan": {"origin": {"provider": "gha", "repository": path, "run_id": "42", "attempt": 1,
                                  "commit": COMMIT, "ref": "refs/heads/main"}}}
    with pytest.raises(lifecycle.PipelineError, match="ancestor-native-finalization-required"):
        module._released(record, {"repository": repository, "records": {}})
    with pytest.raises(lifecycle.PipelineError, match="ancestor-repository-mismatch"):
        module._released(record, {"repository": "https://git.contoso.com/other/factory", "records": {}})


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
