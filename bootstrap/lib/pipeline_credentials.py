"""Opt-in seeded credentials, scoped to one trusted post-login child process.

The seeding vault, federated identity and runner are external prerequisites and
must survive lifecycle teardown. This module never logs in, creates a secret,
changes permissions, exports a job variable, or writes credential files.
ADO provider tokens are OAuth bearer tokens, not PATs (the native state adapter
uses Bearer authentication). Local dispatch retains its separate PAT support.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


DISPATCH_ENV_GROUPS = (frozenset({"GH_TOKEN", "GITHUB_TOKEN"}),
                       frozenset({"SYSTEM_ACCESSTOKEN", "AZURE_DEVOPS_EXT_PAT"}))
DISPATCH_ENV_KEYS = frozenset().union(*DISPATCH_ENV_GROUPS)
MAX_ENV_BYTES = 64 * 1024
SECRET_ID = re.compile(
    r"https://(?P<vault>[a-z][a-z0-9-]{1,22}[a-z0-9])\.vault\.azure\.net"
    r"/secrets/(?P<secret>[A-Za-z0-9-]{1,127})(?:/(?P<version>[a-fA-F0-9]{32}))?")


class CredentialError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise CredentialError(code)


def _setting(environment, name):
    value = environment.get(name, "")
    # Azure Pipelines leaves an optional, undefined macro unchanged.
    return "" if value == "$(" + name + ")" else value


def _token(value):
    require(isinstance(value, str) and 1 <= len(value) <= 32768
            and all(33 <= ord(char) <= 126 for char in value), "provider-token-invalid")
    return value


def _secret_identity(value, code):
    match = SECRET_ID.fullmatch(value) if isinstance(value, str) else None
    require(match is not None and "--" not in match["vault"], code)
    return match.groupdict()


def _azure(command, environment, runner, code):
    try:
        result = runner(["az", *command, "--only-show-errors", "--output", "json"],
                        env=environment, capture_output=True, text=True, timeout=60, shell=False)
        require(result.returncode == 0, code)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise CredentialError(code) from None


def provider_environment(provider, *, environ=None, runner=None):
    """Return a child environment; the caller's environment is never mutated.

    Invoke only after the isolated job's OIDC/WIF login. The account probe verifies
    a usable Azure session before a read; the template owns authentication.
    Native vault/secret identity must match. Derived version/expiry metadata is
    not retrieval authority: GET authorization and network success decide.
    A failed opt-in never falls back to a protected secret or job token.
    """
    require(provider in ("gha", "ado"), "credential-provider-invalid")
    environment = dict(os.environ if environ is None else environ)
    source = _setting(environment, "ESAF_PROVIDER_CREDENTIAL_SOURCE") or "protected-secret"
    reference = _setting(environment, "ESAF_PROVIDER_TOKEN_SECRET_ID")
    require(source in ("protected-secret", "keyvault"), "credential-source-invalid")
    if source == "keyvault":
        requested = _secret_identity(reference, "keyvault-secret-id-required")
        runner = runner or subprocess.run
        azure_environment = dict(environment, AZURE_LOGGING_ENABLE_LOG_FILE="false",
                                 AZURE_CORE_COLLECT_TELEMETRY="false")
        _azure(["account", "show"], azure_environment, runner, "azure-login-required")
        raw = _azure(["keyvault", "secret", "show", "--id", reference, "--query", "{value:value,id:id}"],
                     azure_environment, runner, "keyvault-credential-unavailable")
        try:
            require(len(raw) <= 64 * 1024, "provider-token-invalid")
            payload = json.loads(raw)
        except (ValueError, TypeError):
            raise CredentialError("provider-token-invalid") from None
        require(isinstance(payload, dict), "keyvault-secret-identity-mismatch")
        actual = _secret_identity(payload.get("id"), "keyvault-secret-identity-mismatch")
        require(all(actual[key].casefold() == requested[key].casefold() for key in ("vault", "secret")),
                "keyvault-secret-identity-mismatch")
        token = _token(payload.get("value"))
        if requested["version"] and requested["version"].casefold() != (actual["version"] or "").casefold():
            print(json.dumps({"warning": "keyvault-secret-version-drift"}), file=sys.stderr)
    else:
        require(not reference, "keyvault-opt-in-required")
        token = _setting(environment, "ESAF_PROVIDER_TOKEN") or _setting(
            environment, "GH_TOKEN" if provider == "gha" else "SYSTEM_ACCESSTOKEN")
        require(bool(token), "provider-token-required")
        token = _token(token)
    environment.pop("ESAF_PROVIDER_TOKEN", None)
    if provider == "gha":
        environment["GH_TOKEN"] = token
    else:
        environment["AIFACTORY_STATE_TOKEN"] = token
        environment["SYSTEM_ACCESSTOKEN"] = token
    return environment


def environment_file_path(value):
    """Environment files cannot be transported as pipeline JSON or ZIP inputs."""
    return any(part.casefold() == ".env" or part.casefold().startswith(".env.")
               or part.casefold().endswith(".env") for part in str(value).replace("\\", "/").split("/"))


def load_dispatch_env(path, *, environ=None):
    """Load only an explicit, untracked local file; never source/eval/expand it.

    UTF-8 KEY=value assignments, optional `export`, whole-value single/double
    quotes, blank lines and full-line comments are supported. No interpolation,
    escaping or inline comment expansion occurs. Only dispatch token names are
    allowed; any exported credential (even empty) takes precedence over that
    provider's aliases in the file.
    """
    environment = os.environ if environ is None else environ
    path = Path(path).absolute()
    try:
        require(not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_ENV_BYTES,
                "bounded-ordinary-env-file-required")
        tracked = subprocess.run(["git", "-C", str(path.parent), "ls-files", "--error-unmatch", "--", path.name],
                                 capture_output=True, text=True, timeout=30, shell=False)
        require(tracked.returncode != 0, "env-file-must-not-be-tracked")
        with path.open("rb") as stream:
            raw = stream.read(MAX_ENV_BYTES + 1)
        require(len(raw) <= MAX_ENV_BYTES, "bounded-ordinary-env-file-required")
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise CredentialError("env-file-unavailable") from None
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name, value = name.strip(), value.strip()
        require(separator and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name), "env-file-assignment-invalid")
        require(name in DISPATCH_ENV_KEYS, "env-file-name-not-allowed")
        require(name not in values, "env-file-duplicate-name")
        if value.startswith(("'", '"')):
            require(len(value) >= 2 and value[-1] == value[0], "env-file-quotes-invalid")
            value = value[1:-1]
        require(all(32 <= ord(char) <= 126 for char in value), "env-file-value-invalid")
        values[name] = value
    inherited = set(environment)
    for group in DISPATCH_ENV_GROUPS:
        if not inherited & group:
            for name in group & values.keys():
                environment[name] = values[name]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("gha", "ado"), required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        require(bool(command), "trusted-child-command-required")
        environment = provider_environment(args.provider)
        return subprocess.run(command, env=environment, shell=False).returncode
    except (CredentialError, OSError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, CredentialError) else "credential-child-unavailable"
        print(json.dumps({"outcome": "not-completed", "error": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
