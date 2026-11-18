"""The one place that knows the three kinds of GitHub host, so every bootstrap module agrees (a Strategy keyed by host).

Contract (decided 2026-11-18): ``github_repository`` = ``[HOST/]OWNER/REPO``. Plain ``OWNER/REPO`` is github.com and
behaves exactly as before; another host is written in front, as gh's ``--repo HOST/OWNER/REPO``.

- github.com: REST ``https://api.github.com``, OIDC issuer ``https://token.actions.githubusercontent.com``,
  tokens GH_TOKEN / GITHUB_TOKEN.
- GHE.com data residency (``SUB.ghe.com``): REST ``https://api.SUB.ghe.com``, OIDC issuer
  ``https://token.actions.SUB.ghe.com`` (docs.github.com/en/enterprise-cloud@latest/admin/data-residency/
  feature-overview-for-github-enterprise-cloud-with-data-residency, "URL differences"), tokens as github.com (gh).
- GitHub Enterprise Server (any other host): REST ``https://HOST/api/v3`` (docs.github.com/en/enterprise-server@latest/
  rest/guides/getting-started-with-the-rest-api), OIDC issuer ``https://HOST/_services/token`` (docs.github.com/en/
  enterprise-server@latest/actions/security-for-github-actions/security-hardening-your-deployments/
  about-security-hardening-with-openid-connect), tokens GH_ENTERPRISE_TOKEN / GITHUB_ENTERPRISE_TOKEN (gh), so a
  github.com token is never sent to it.

Rules for callers: ``gh api --hostname HOST repos/OWNER/REPO/...`` (``repo.path``); gh subcommands take
``--repo repo.gh_repo``. Mirrors MAUI ESAIF.DomainLayer Tutorials/GitHubHost.cs. ``python github_host.py fields VALUE``
prints host, path, slug, url and issuer (one per line) for the bash bootstrap.
"""

from __future__ import annotations

import os
import re
import sys
from typing import NamedTuple
from urllib.parse import urlsplit

DOTCOM = "github.com"
DOTCOM_ISSUER = "https://token.actions.githubusercontent.com"
_DATA_RESIDENCY = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.ghe\.com")
_HOST = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,38})")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")
# Hosts people paste by mistake that are not GitHub; a GitHub Enterprise Server can have any other name.
_NOT_GITHUB = ("gitlab.com", "bitbucket.org", "dev.azure.com", "visualstudio.com")
FORMAT_HINT = "Use OWNER/REPO for github.com or HOST/OWNER/REPO (https://HOST/OWNER/REPO) for GitHub Enterprise."


class GitHubHostError(ValueError):
    """The value is not a GitHub repository or host this bootstrap can target."""


def normalize_host(host) -> str:
    return str(host or "").strip().lower()


def is_valid_host(host) -> bool:
    name = normalize_host(host)
    if name == DOTCOM:
        return True
    if not _HOST.fullmatch(name) or name.endswith("." + DOTCOM):
        return False
    if name == "ghe.com" or name.endswith(".ghe.com"):
        return bool(_DATA_RESIDENCY.fullmatch(name))
    return not any(name == other or name.endswith("." + other) for other in _NOT_GITHUB)


def _require_host(host) -> str:
    name = normalize_host(host)
    if not is_valid_host(name):
        raise GitHubHostError(f"'{host}' is not a GitHub host. {FORMAT_HINT}")
    return name


def is_dotcom(host) -> bool:
    return normalize_host(host) == DOTCOM


def is_data_residency(host) -> bool:
    return bool(_DATA_RESIDENCY.fullmatch(normalize_host(host)))


def is_enterprise_server(host) -> bool:
    """GitHub Enterprise Server: neither github.com nor a GHE.com data residency host."""
    return not is_dotcom(host) and not is_data_residency(host)


def api_base_for(host) -> str:
    """REST API root without a trailing slash: callers append ``/`` + endpoint."""
    name = _require_host(host)
    if name == DOTCOM:
        return "https://api.github.com"
    return f"https://{name}/api/v3" if is_enterprise_server(name) else f"https://api.{name}"


def api_hostname_for(host) -> str:
    return urlsplit(api_base_for(host)).hostname


def oidc_issuer_for(host) -> str:
    """The ``iss`` of GitHub Actions OIDC tokens, which a federated credential must match byte for byte."""
    name = _require_host(host)
    if name == DOTCOM:
        return DOTCOM_ISSUER
    return f"https://{name}/_services/token" if is_enterprise_server(name) else f"https://token.actions.{name}"


def host_for_oidc_issuer(issuer) -> str | None:
    """The GitHub host whose Actions sign tokens with this issuer, or None."""
    value = str(issuer or "")
    if value == DOTCOM_ISSUER:
        return DOTCOM
    parts = urlsplit(value)
    hostname = parts.hostname or ""
    if parts.scheme != "https" or parts.port or parts.username or parts.query or parts.fragment:
        return None
    if parts.path == "" and hostname.startswith("token.actions."):
        candidate = hostname.removeprefix("token.actions.")
        return candidate if is_data_residency(candidate) else None
    if parts.path == "/_services/token" and is_valid_host(hostname) and is_enterprise_server(hostname):
        return hostname
    return None


def is_actions_token_request_host(host, hostname) -> bool:
    """Whether ACTIONS_ID_TOKEN_REQUEST_URL's hostname belongs to this GitHub host's Actions service.

    github.com: ``*.actions.githubusercontent.com``; GHE.com: ``*.actions.SUB.ghe.com`` (docs network details list
    ``*.actions.SUBDOMAIN.ghe.com``); GHES serves Actions from its own hostname."""
    name, candidate = normalize_host(host), normalize_host(hostname)
    if name == DOTCOM:
        return bool(re.fullmatch(r"[a-z0-9-]+\.actions\.githubusercontent\.com", candidate))
    if is_data_residency(name):
        return bool(re.fullmatch(r"[a-z0-9-]+\.actions\." + re.escape(name), candidate))
    return is_valid_host(name) and candidate == name


def token_variables(host) -> tuple[str, str]:
    """The environment variables gh reads a token for this host from, in order."""
    if is_enterprise_server(host):
        return ("GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
    return ("GH_TOKEN", "GITHUB_TOKEN")


def token_from_environment(host, environ=None) -> str:
    environ = os.environ if environ is None else environ
    for name in token_variables(host):
        if environ.get(name):
            return environ[name]
    return ""


def login_command(host) -> str:
    return "gh auth login" if is_dotcom(host) else "gh auth login --hostname " + normalize_host(host)


class GitHubRepository(NamedTuple):
    """Immutable; a NamedTuple (not a dataclass) so loaders that skip sys.modules can import it."""

    host: str
    owner: str
    name: str

    @property
    def path(self) -> str:
        """OWNER/REPO, as REST ``repos/`` endpoints and the token's full_name use it."""
        return f"{self.owner}/{self.name}"

    @property
    def slug(self) -> str:
        """The github_repository value: OWNER/REPO on github.com, HOST/OWNER/REPO elsewhere."""
        return self.path if self.host == DOTCOM else f"{self.host}/{self.path}"

    @property
    def gh_repo(self) -> str:
        """``gh --repo`` value with an explicit host, so GH_HOST never redirects it."""
        return f"{self.host}/{self.path}"

    @property
    def url(self) -> str:
        return f"https://{self.host}/{self.path}"

    @property
    def api_base(self) -> str:
        return api_base_for(self.host)

    @property
    def oidc_issuer(self) -> str:
        return oidc_issuer_for(self.host)


def parse_github_repository(value) -> GitHubRepository:
    """Parse OWNER/REPO, HOST/OWNER/REPO, https://HOST/OWNER/REPO[.git][/] or git@HOST:OWNER/REPO[.git]."""
    text = str(value or "").strip()
    ssh = re.fullmatch(r"git@([^:/\s]+):([^\s]+)", text)
    if ssh:
        host, rest = ssh[1], ssh[2]
    elif "://" in text:
        parts = urlsplit(text)
        if parts.scheme != "https" or parts.username or parts.password or parts.query or parts.fragment:
            raise GitHubHostError(f"'{text}' is not an https GitHub repository URL. {FORMAT_HINT}")
        try:
            port = parts.port
        except ValueError:
            port = -1
        if port is not None:
            raise GitHubHostError(f"'{text}' names a port. {FORMAT_HINT}")
        host, rest = parts.hostname or "", parts.path
    else:
        segments = text.split("/")
        host, rest = (segments[0], "/".join(segments[1:])) if len(segments) == 3 else (DOTCOM, text)
    segments = rest.strip("/").split("/") if rest.strip("/") else []
    if len(segments) != 2:
        raise GitHubHostError(f"'{text}' is not a GitHub repository. {FORMAT_HINT}")
    owner, name = segments[0], segments[1].removesuffix(".git")
    if not _OWNER.fullmatch(owner) or not _REPO.fullmatch(name) or name in (".", ".."):
        raise GitHubHostError(f"'{text}' has an invalid owner or repository name. {FORMAT_HINT}")
    return GitHubRepository(_require_host(host), owner, name)


def repository_url(value) -> str:
    return parse_github_repository(value).url


def slug_from_url(value) -> str:
    return parse_github_repository(value).slug


def same_repository(left, right) -> bool:
    try:
        a, b = parse_github_repository(left), parse_github_repository(right)
    except GitHubHostError:
        return False
    return a.host == b.host and a.path.lower() == b.path.lower()


def main(argv) -> int:
    if len(argv) != 3 or argv[1] != "fields":
        print("usage: github_host.py fields [HOST/]OWNER/REPO", file=sys.stderr)
        return 2
    try:
        repo = parse_github_repository(argv[2])
    except GitHubHostError as error:
        print(str(error), file=sys.stderr)
        return 2
    print("\n".join((repo.host, repo.path, repo.slug, repo.url, repo.oidc_issuer)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
