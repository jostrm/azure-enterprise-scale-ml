"""github_repository = [HOST/]OWNER/REPO (decided 2026-11-18): one host module for github.com, GHE.com and GHES.

Offline: no GitHub host is contacted. Mirrors the MAUI ESAIF.DomainLayer Tutorials/GitHubHost.cs strategy.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
LIB = ROOT / "bootstrap" / "lib"
SPEC = importlib.util.spec_from_file_location("github_host", LIB / "github_host.py")
gh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gh)


@pytest.mark.parametrize("value", [
    "contoso/aifactory", "https://github.com/contoso/aifactory", "https://github.com/contoso/aifactory.git",
    "https://github.com/contoso/aifactory/", "github.com/contoso/aifactory", "git@github.com:contoso/aifactory.git",
    "GitHub.com/contoso/aifactory",
])
def test_plain_owner_repo_stays_github_com_exactly_as_today(value):
    repo = gh.parse_github_repository(value)
    assert (repo.host, repo.owner, repo.name) == ("github.com", "contoso", "aifactory")
    assert repo.slug == "contoso/aifactory"              # github_repository keeps the old form
    assert repo.path == "contoso/aifactory"
    assert repo.url == "https://github.com/contoso/aifactory"
    assert repo.gh_repo == "github.com/contoso/aifactory"
    assert repo.api_base == "https://api.github.com"
    assert repo.oidc_issuer == "https://token.actions.githubusercontent.com"


@pytest.mark.parametrize("value", [
    "contoso.ghe.com/research/aifactory", "https://contoso.ghe.com/research/aifactory",
    "https://CONTOSO.ghe.com/research/aifactory.git", "git@contoso.ghe.com:research/aifactory.git",
])
def test_ghe_com_data_residency_host(value):
    repo = gh.parse_github_repository(value)
    assert (repo.host, repo.owner, repo.name) == ("contoso.ghe.com", "research", "aifactory")
    assert repo.slug == "contoso.ghe.com/research/aifactory"
    assert repo.path == "research/aifactory"
    assert repo.url == "https://contoso.ghe.com/research/aifactory"
    assert repo.gh_repo == "contoso.ghe.com/research/aifactory"
    # docs.github.com enterprise-cloud data residency: api.SUBDOMAIN.ghe.com and token.actions.SUBDOMAIN.ghe.com
    assert repo.api_base == "https://api.contoso.ghe.com"
    assert repo.oidc_issuer == "https://token.actions.contoso.ghe.com"


def test_enterprise_server_host():
    repo = gh.parse_github_repository("https://git.contoso.com/platform/aifactory")
    assert repo.slug == "git.contoso.com/platform/aifactory"
    assert repo.api_base == "https://git.contoso.com/api/v3"
    assert repo.oidc_issuer == "https://git.contoso.com/_services/token"
    assert gh.is_enterprise_server("git.contoso.com") and not gh.is_enterprise_server("contoso.ghe.com")


@pytest.mark.parametrize("value", [
    "", "contoso", "contoso/", "/aifactory", "a/b/c/d", "http://github.com/contoso/aifactory",
    "https://user:pw@github.com/contoso/aifactory", "https://github.com:8443/contoso/aifactory",
    "https://10.0.0.4/contoso/aifactory", "https://www.github.com/contoso/aifactory", "ghe.com/contoso/aifactory",
    "https://gitlab.com/contoso/aifactory", "https://dev.azure.com/contoso/project/_git/aifactory",
    "contoso/..", "-contoso/aifactory", "contoso/aif factory", "https://github.com/contoso/aifactory?x=1",
])
def test_rejects_non_github_or_malformed_values(value):
    with pytest.raises(gh.GitHubHostError):
        gh.parse_github_repository(value)


def test_api_base_and_issuer_by_host():
    assert gh.api_base_for("github.com") == "https://api.github.com"
    assert gh.api_base_for("contoso.ghe.com") == "https://api.contoso.ghe.com"
    assert gh.api_base_for("git.contoso.com") == "https://git.contoso.com/api/v3"
    assert gh.api_hostname_for("github.com") == "api.github.com"
    assert gh.api_hostname_for("contoso.ghe.com") == "api.contoso.ghe.com"
    assert gh.api_hostname_for("git.contoso.com") == "git.contoso.com"
    assert gh.oidc_issuer_for("github.com") == "https://token.actions.githubusercontent.com"
    assert gh.oidc_issuer_for("contoso.ghe.com") == "https://token.actions.contoso.ghe.com"
    assert gh.oidc_issuer_for("git.contoso.com") == "https://git.contoso.com/_services/token"
    with pytest.raises(gh.GitHubHostError):
        gh.api_base_for("gitlab.com")


def test_issuer_maps_back_to_its_host_only():
    assert gh.host_for_oidc_issuer("https://token.actions.githubusercontent.com") == "github.com"
    assert gh.host_for_oidc_issuer("https://token.actions.contoso.ghe.com") == "contoso.ghe.com"
    assert gh.host_for_oidc_issuer("https://git.contoso.com/_services/token") == "git.contoso.com"
    assert gh.host_for_oidc_issuer("https://evil.example/token") is None


def test_actions_token_request_host_is_host_specific():
    assert gh.is_actions_token_request_host("github.com", "pipelinesghubeus6.actions.githubusercontent.com")
    assert not gh.is_actions_token_request_host("github.com", "pipelines.actions.contoso.ghe.com")
    assert gh.is_actions_token_request_host("contoso.ghe.com", "pipelines.actions.contoso.ghe.com")
    assert not gh.is_actions_token_request_host("contoso.ghe.com", "x.actions.githubusercontent.com")
    assert gh.is_actions_token_request_host("git.contoso.com", "git.contoso.com")
    assert not gh.is_actions_token_request_host("git.contoso.com", "evil.contoso.com")


def test_token_variables_never_send_a_github_com_token_to_enterprise_server():
    assert gh.token_variables("github.com") == ("GH_TOKEN", "GITHUB_TOKEN")
    assert gh.token_variables("contoso.ghe.com") == ("GH_TOKEN", "GITHUB_TOKEN")      # as gh reads them
    assert gh.token_variables("git.contoso.com") == ("GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
    env = {"GH_TOKEN": "dotcom-token"}
    assert gh.token_from_environment("github.com", env) == "dotcom-token"
    assert gh.token_from_environment("git.contoso.com", env) == ""
    assert gh.token_from_environment("git.contoso.com", {"GITHUB_ENTERPRISE_TOKEN": "ghes"}) == "ghes"


def test_gh_argv_helpers_keep_github_com_argv_and_target_the_host_elsewhere():
    assert gh.login_command("github.com") == "gh auth login"
    assert gh.login_command("contoso.ghe.com") == "gh auth login --hostname contoso.ghe.com"


def test_slug_from_url_round_trips_and_handles_route_urls():
    assert gh.slug_from_url("https://github.com/contoso/aifactory.git") == "contoso/aifactory"
    assert gh.slug_from_url("https://contoso.ghe.com/research/aifactory") == "contoso.ghe.com/research/aifactory"
    assert gh.repository_url("contoso/aifactory") == "https://github.com/contoso/aifactory"
    assert gh.repository_url("contoso.ghe.com/research/aifactory") == "https://contoso.ghe.com/research/aifactory"
    assert gh.same_repository("CONTOSO/aifactory", "https://github.com/contoso/AIFactory.git")
    assert not gh.same_repository("contoso/aifactory", "contoso.ghe.com/contoso/aifactory")


def test_cli_prints_the_fields_bash_needs():
    result = subprocess.run([sys.executable, "-B", str(LIB / "github_host.py"), "fields",
                             "https://contoso.ghe.com/research/aifactory"], capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [
        "contoso.ghe.com", "research/aifactory", "contoso.ghe.com/research/aifactory",
        "https://contoso.ghe.com/research/aifactory", "https://token.actions.contoso.ghe.com"]
    bad = subprocess.run([sys.executable, "-B", str(LIB / "github_host.py"), "fields", "gitlab.com/a/b"],
                         capture_output=True, text=True)
    assert bad.returncode == 2 and "HOST/OWNER/REPO" in bad.stderr
