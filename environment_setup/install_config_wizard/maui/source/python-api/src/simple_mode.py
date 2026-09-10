"""Confirmed, owner-bound execution of the fixed private/Dev bootstrap.

No raw process output, credentials, or advanced-editor state enter persistence.
The only write performed by prepare is its immutable SQLite confirmation.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src import azure_auth, operations, release_version
from src.ticket_connectors import TicketError
from src.ticketing import AzureTicketIdentity


APP_ROOT = Path(__file__).resolve().parent.parent


def accelerator_root():
    configured = os.environ.get("AIFACTORY_ACCELERATOR_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    sibling = APP_ROOT.parent / "azure-enterprise-scale-ml"
    if sibling.is_dir():
        return sibling
    return Path(r"C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml")


SCRIPT = accelerator_root() / "bootstrap" / "GHA-create-new-aifactory-scaleset.sh"
SUPPORTED_REGIONS = (
    "swedencentral", "westeurope", "northeurope", "eastus", "eastus2", "uksouth", "germanywestcentral",
)
GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
FIELDS = {
    "subscription_id": (36, GUID), "tenant_id": (36, GUID),
    "location": (40, r"[a-z][a-z0-9]{1,39}"),
    "factory_prefix": (12, r"[a-z][a-z0-9-]{1,10}-"),
    "github_repository": (140, LOGIN + r"/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"),
    "team_member_email": (254, r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,127}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,120})\.[A-Za-z]{2,24}"),
    "team_group_name": (120, r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}"),
    "cost_center": (32, r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}"),
    "repo_root": (240, None),
}
OPTIONAL_FIELDS = {
    "github_visibility", "project_resources", "app_gateway_backend_fqdn",
    "app_gateway_hostname", "app_gateway_certificate_secret_id",
    "aifactory_version",
}
RESOURCE_ID = r"[a-z][a-z0-9-]{0,63}"
REQUIRED_PROJECT_RESOURCES = {"storage", "key-vault", "managed-identities"}
GATEWAY_FIELDS = ("app_gateway_backend_fqdn", "app_gateway_hostname", "app_gateway_certificate_secret_id")
GATEWAY_ENV_FIELDS = {
    "app_gateway_backend_fqdn": "AIF_APP_GATEWAY_BACKEND_FQDN",
    "app_gateway_hostname": "AIF_APP_GATEWAY_HOSTNAME",
    "app_gateway_certificate_secret_id": "AIF_APP_GATEWAY_CERT_SECRET_ID",
}
PUBLIC_REPOSITORY_WARNING = (
    "Generated repository content and GitHub Actions logs may be public; Azure network privacy settings are unchanged. "
    ".env, variables.json, VPN profile/secrets are never committed."
)
FIXED_ENV = {
    "AIF_SIMPLE_MODE": "true", "AIF_TOPOLOGY": "s", "AIF_NETWORK_MODE": "priv",
    "AIF_IDENTITY_MODE": "c", "AIF_SEEDING_MODE": "c", "AIF_SEED_PROJECT_SP": "false",
    "AIF_SETUP_HUB_ACCESS": "true", "AIF_CONFIGURE_VPN_CLIENT": "false",
    "AIF_ACCESS_HUB_MODE": "i", "AIF_DEV_VNET_CIDR": "172.16.0.0/20",
    "AIF_SCALESET_SUFFIX": "001", "AIF_PROJECT_NUMBER": "001",
}
ENV_FIELDS = {
    "subscription_id": "AIF_DEV_SUBSCRIPTION_ID", "tenant_id": "AIF_TENANT_ID",
    "location": "AIF_LOCATION", "factory_prefix": "AIF_PREFIX",
    "github_repository": "GITHUB_REPOSITORY", "team_member_email": "AIF_TEAM_MEMBER_EMAIL",
    "team_group_name": "AIF_TEAM_GROUP_NAME", "cost_center": "AIF_COST_CENTER",
}
REQUIREMENTS = [
    "Install Git for Windows (Git Bash), git, Azure CLI, GitHub CLI, and Python 3 on the API host.",
    "Sign in separately using the host az and gh CLI caches; no password or PAT is accepted by this form.",
    "Use an existing Dev subscription: Owner or equivalent resource + RBAC + policy-assignment privileges "
    "(Contributor + User Access Administrator, or Contributor + Role Based Access Control Administrator + Resource Policy Contributor).",
    "Entra group creation/membership and first-party service-principal lookup require separate tenant permissions; "
    "Groups Administrator may be needed if tenant policy restricts group creation. Global Administrator is not a default requirement.",
    "GitHub needs repository creation for the selected visibility, contents/workflows write, environments/secrets/variables administration, "
    "and Actions dispatch. Organizations may additionally require SSO authorization and permit repository creation.",
    "Publish the updated purple bootstrap and its dependencies to the configured source branch before creation.",
]
WARNINGS = [
    "Azure role assignments are not a complete effective-permission test: deny assignments, conditions, PIM activation, "
    "tenant restrictions, resource policy, quota and regional service/SKU availability may still prevent deployment.",
    "Entra group/membership, service-principal lookup, GitHub organization SSO/creation policy and Actions policy "
    "are not fully verified by read-only preflight.",
    "Do not change the shared host az/gh sign-in while a creation job is running.",
    "A failed or interrupted deployment may have created billable resources. Inspect it before any new attempt; there is no automatic retry.",
]
STAGES = {
    "preflight": "Checking bootstrap prerequisites.",
    "repository": "Preparing the selected GitHub repository and local files.",
    "identity": "Configuring Entra group, managed identity, OIDC and role assignments.",
    "common": "Deploying Dev common infrastructure.",
    "hub": "Deploying and linking the private integrated hub.",
    "project": "Deploying Dev project 001.",
    "completed": "Bootstrap reported deployment completion.",
}
TERMINAL_STAGES = {
    ">> 06 / Azure access": "preflight",
    ">> 07 / Orchestrator repository": "repository",
    ">> 08 / Accelerator and templates": "repository",
    ">> 09 / Deployment identity": "identity",
    ">> 10 / Seeding Key Vault": "identity",
    ">> 11 / Entra team": "identity",
    ">> 13 / GitHub deployment identity": "identity",
    ">> 14 / Check in automation": "repository",
    ">> 15 / Common and project deployment": "common",
    ">> 12 / Hub private DNS": "hub",
    ">> 12a / Hub DNS forwarder": "hub",
    ">> 13 / Spoke private-DNS policy": "hub",
}
ACTIVE = ("queued", "running")
_GLOBAL_LOCK = threading.RLock()
_INITIALIZED_DATABASES: set[str] = set()
_LIVE_JOBS: set[str] = set()


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def safe_metadata(value, maximum=254):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 or ord(c) > 126 for c in value):
        return ""
    return value


def unix_path(path):
    value = str(path).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", value):
        return "/" + value[0].lower() + value[2:]
    return value


def output_stage(line):
    if len(line) > 4096 or not line.endswith("\n"):
        return None
    match = re.fullmatch(r"AIF_SIMPLE_STAGE=([a-z]+)\r?\n", line)
    if match:
        return match[1] if match[1] in STAGES else None
    # Existing purple aif_section/aif_value output is also a supported
    # protocol. Accept only exact headings or numeric run IDs, never their
    # arbitrary text, resource names, errors, or credentials.
    text = re.sub(r"\x1b\[[0-9;]*m", "", line).strip(" \r\n")
    if text in TERMINAL_STAGES:
        return TERMINAL_STAGES[text]
    run = re.fullmatch(r"GitHub (common|project) run +[0-9]{1,20}", text)
    return run[1] if run else None


def launch_environment(explicit, tools=None):
    # All other AIF/ADO/GITHUB variables, tokens, shell startup hooks and git
    # configuration overrides are deliberately absent. gh reads its host cache.
    keep = {
        "PATH", "PATHEXT", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SYSTEMROOT", "WINDIR",
        "COMSPEC", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
        "TEMP", "TMP", "AZURE_CONFIG_DIR", "GH_CONFIG_DIR", "XDG_CONFIG_HOME",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    path_key = next((k for k in env if k.upper() == "PATH"), "PATH")
    additions = [str(Path(v).parent) for v in (tools or {}).values() if Path(v).is_absolute()]
    env[path_key] = os.pathsep.join(dict.fromkeys(additions + [env.get(path_key, "")]))
    env.update({
        "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never", "GH_PROMPT_DISABLED": "1",
        "GH_HOST": "github.com", "AZURE_CORE_LOGIN_EXPERIENCE_V2": "off",
        "AZURE_CORE_ENABLE_BROKER_ON_WINDOWS": "false", "AZURE_CORE_LOG_LEVEL": "critical",
        "AZURE_LOGGING_ENABLE_LOG_FILE": "false", "PYTHONUNBUFFERED": "1",
    })
    env.update(explicit)
    return env


class ReadOnlyCLI:
    """A narrow read-only CLI adapter; injected runners never trigger discovery."""

    def __init__(self, runner=None):
        self.runner = runner or subprocess.run
        self.injected = runner is not None

    def tools(self):
        if self.injected:
            return {name: name for name in ("az", "gh", "git", "bash", "python")}
        found = {}
        try:
            found["az"] = operations.resolve_azure_cli()
            operations._azure_cli_command(found["az"])
        except (RuntimeError, OSError):
            pass
        found["python"] = sys.executable
        for name in ("gh", "git"):
            path = shutil.which(name)
            if path and Path(path).suffix.casefold() not in {".cmd", ".bat"}:
                found[name] = path
        if sys.platform == "win32":
            program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            for name, relative in (("git", ("Git", "cmd", "git.exe")), ("gh", ("GitHub CLI", "gh.exe"))):
                candidate = program_files.joinpath(*relative)
                if name not in found and candidate.is_file():
                    found[name] = str(candidate)
            candidates = [
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
                Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "Git" / "bin" / "bash.exe",
            ]
            if "git" in found:
                candidates.insert(0, Path(found["git"]).parent.parent / "bin" / "bash.exe")
            found_bash = next((p for p in candidates if p.is_file()), None)
        else:
            found_bash = shutil.which("bash")
        if found_bash:
            found["bash"] = str(found_bash)
        return found

    def read(self, tool, arguments, *, raw=False, allow_missing=False, allow_empty=False):
        tools = self.tools()
        if tool not in tools:
            raise TicketError(f"Install {tool} on the API host and retry.", 409)
        prefix = [tools[tool]]
        if tool == "az" and not self.injected:
            prefix = operations._azure_cli_command(tools["az"])
        try:
            result = self.runner(
                [*prefix, *arguments], shell=False, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=45, env=launch_environment({}, tools),
            )
        except (OSError, subprocess.SubprocessError):
            raise TicketError(f"Could not complete the read-only {tool} check. Check host tools, sign-in and connectivity.", 409) from None
        if result.returncode:
            # Only a structured HTTP 404 is a candidate for absence; callers
            # additionally prove administration of the destination namespace.
            if allow_missing and re.search(r"^HTTP/\S+ 404(?:\s|$)", result.stdout or "", re.M):
                return None
            if allow_empty and re.search(r"^HTTP/\S+ 409(?:\s|$)", result.stdout or "", re.M):
                _, error = self._http(result.stdout)
                if error.get("message", "").casefold().rstrip(".") == "git repository is empty":
                    return []
            raise TicketError(f"The read-only {tool} check failed. Check host sign-in, access and connectivity; no changes were made.", 409)
        if len(result.stdout or "") > 2_000_000:
            raise TicketError(f"The read-only {tool} response was unexpectedly large.", 409)
        if raw:
            return result.stdout
        try:
            return json.loads(result.stdout)
        except (ValueError, TypeError):
            raise TicketError(f"Could not verify the read-only {tool} response.", 409) from None

    def _run(self, arguments):
        return self.read("az", [*arguments, "--only-show-errors"])

    def accounts(self):
        raw = self._run([
            "account", "list", "--all", "--query",
            "[].{id:id,tenantId:tenantId,name:name,accountName:user.name,isDefault:isDefault,state:state}",
            "--output", "json",
        ])
        if not isinstance(raw, list):
            raise TicketError("Could not read Azure account metadata.", 401)
        result = []
        for item in raw:
            if not isinstance(item, dict) or not re.fullmatch(GUID, item.get("id", "")) or not re.fullmatch(GUID, item.get("tenantId", "")):
                continue
            if item.get("state", "Enabled") != "Enabled":
                continue
            result.append({
                "subscription_id": item["id"].lower(), "tenant_id": item["tenantId"].lower(),
                "subscription_name": safe_metadata(item.get("name", "")),
                "account_name": azure_auth._account_name(item.get("accountName", "")),
                "is_default": item.get("isDefault") is True,
            })
        return result

    def _accounts(self):
        return [
            {"id": a["subscription_id"], "tenant_id": a["tenant_id"],
             "account_name": a["account_name"], "is_default": a["is_default"]}
            for a in self.accounts()
        ]

    def github(self):
        raw = self.read("gh", ["api", "--hostname", "github.com", "--include", "user"], raw=True)
        headers, value = self._http(raw)
        login = value.get("login", "")
        if not re.fullmatch(LOGIN, login):
            raise TicketError("Sign in to GitHub CLI on the API host before creation.", 401)
        scopes = set(s.strip() for s in headers.get("x-oauth-scopes", "").split(","))
        return login, scopes

    @staticmethod
    def _http(raw):
        try:
            header, body = raw.replace("\r\n", "\n").split("\n\n", 1)
            headers = dict(line.lower().split(":", 1) for line in header.splitlines()[1:] if ":" in line)
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError
            return headers, value
        except (ValueError, AttributeError):
            raise TicketError("Could not verify the GitHub API response.", 409) from None

    def repository(self, target, login, scopes, visibility="private"):
        owner, name = target.split("/")
        if not {"repo", "workflow"}.issubset(scopes):
            raise TicketError(
                "GitHub CLI authorization could not be verified for private repository and workflow administration. "
                "Use the host gh cached OAuth sign-in with repo and workflow scopes, then prepare again.", 409,
            )
        if owner.casefold() != login.casefold():
            membership = self.read("gh", ["api", "--hostname", "github.com", f"user/memberships/orgs/{owner}"])
            if membership.get("state") != "active" or membership.get("role") != "admin":
                raise TicketError("Organization repository creation requires verified active organization-admin access; check SSO and creation policy.", 409)
        raw = self.read("gh", ["api", "--hostname", "github.com", "--include", f"repos/{target}"], raw=True, allow_missing=True)
        if raw is None:
            return {"state": "absent", "owner": owner.lower(), "name": name.lower(), "visibility": visibility}
        _, repo = self._http(raw)
        if (repo.get("full_name", "").casefold() != target.casefold()
                or repo.get("private") is not (visibility == "private") or repo.get("archived")):
            raise TicketError(
                f"The existing destination must be the specified {visibility}, non-archived repository. "
                "Existing repository visibility is never changed.", 409,
            )
        if repo.get("permissions", {}).get("admin") is not True:
            raise TicketError("Administrator rights on the existing GitHub repository could not be verified.", 409)
        # No-content and no-refs checks avoid trusting GitHub's cached size field.
        refs_raw = self.read("gh", ["api", "--hostname", "github.com", "--include", f"repos/{target}/git/matching-refs/"],
                             raw=True, allow_empty=True)
        if refs_raw == []:
            refs = []
        else:
            try:
                refs = json.loads(refs_raw.replace("\r\n", "\n").split("\n\n", 1)[1])
            except (ValueError, IndexError, AttributeError):
                raise TicketError("Could not verify that the existing GitHub repository is empty.", 409) from None
        if not isinstance(refs, list) or refs or repo.get("size") != 0:
            raise TicketError("The GitHub repository is not empty. Choose a new name; existing content will not be stashed or overwritten.", 409)
        return {"state": "empty", "id": repo.get("id"), "owner": owner.lower(), "name": name.lower(), "visibility": visibility}

    def roles(self, subscription, oid):
        roles = self._run([
            "role", "assignment", "list", "--assignee-object-id", oid,
            "--scope", f"/subscriptions/{subscription}", "--subscription", subscription, "--include-inherited", "--all",
            "--query", "[].{role:roleDefinitionName,scope:scope,condition:condition}", "--output", "json",
        ])
        if not isinstance(roles, list):
            raise TicketError("Could not verify Azure subscription role assignments.", 409)
        names = {
            r.get("role") for r in roles if isinstance(r, dict) and not r.get("condition")
            and (r.get("scope", "").casefold() in {"/", f"/subscriptions/{subscription}".casefold()}
                 or re.fullmatch(r"/providers/microsoft.management/managementgroups/[a-z0-9_.()-]+",
                                 r.get("scope", "").casefold()))
        }
        sufficient = "Owner" in names or {"Contributor", "User Access Administrator"}.issubset(names) or {
            "Contributor", "Role Based Access Control Administrator", "Resource Policy Contributor"
        }.issubset(names)
        if not sufficient:
            raise TicketError(
                "Dev subscription resource, RBAC and policy privileges could not all be verified. "
                "Use active Owner, Contributor + User Access Administrator, or "
                "Contributor + Role Based Access Control Administrator + Resource Policy Contributor, "
                "or have an administrator verify equivalent custom/inherited permissions before proceeding.", 409,
            )


class ScopedIdentityAuth:
    def __init__(self, cli, account):
        self.cli, self.account = cli, account

    def _accounts(self):
        a = self.account
        return [{"id": a["subscription_id"], "tenant_id": a["tenant_id"],
                 "account_name": a["account_name"], "is_default": True}]

    def _run(self, args):
        return self.cli._run(args)


class SourceReadiness:
    def __init__(self, cli, script=SCRIPT):
        self.cli, self.script = cli, script
        self.root = script.parent.parent

    def manifest(self):
        try:
            return self._contract(self.root / "bootstrap" / "lib" / "aifactory_scaleset_config.py")
        except (OSError, ValueError, TypeError, AttributeError, SyntaxError):
            return {}

    def check(self, aifactory_version=None):
        selected = release_version.select(aifactory_version)
        contract = {}
        try:
            selected = release_version.resolve(selected, self.cli)
            ref = selected["resolved_ref"]
            def show(path):
                return self.cli.read("git", ["-C", str(self.root), "show", ref + ":" + path], raw=True)
            text = show("bootstrap/lib/create-new-aifactory-scaleset.sh")
            contract = self._contract_text(show("bootstrap/lib/aifactory_scaleset_config.py"))
            if (contract.get("contractVersion") != 2 or not contract.get("resourceCatalog")
                    or release_version.CONTRACT not in text
                    or release_version.CONTRACT not in show("bootstrap/lib/release_version.py")
                    or any(token not in text for token in (
                        "GITHUB_REPOSITORY_VISIBILITY", "AIF_SIMPLE_PROJECT_RESOURCES_JSON",
                        "AIF_SUBMODULE_REF", "--verify-simple-mode-source"))):
                raise ValueError("Selected release lacks the required Simple Mode and version contract.")
            self.cli.read("git", ["-C", str(self.root), "cat-file", "-e", ref + ":environment_setup/aifactory"], raw=True)
            return {"blockers": [], "fingerprint": ref, "commit": ref, **selected, "preset": contract}
        except (OSError, ValueError, TypeError, AttributeError, SyntaxError, TicketError):
            return {"blockers": [
                "Publish/fetch the selected release with compatible Simple Mode v2 and version contracts. "
                "Its exact published commit must be available locally; no fallback to development main or dirty working files is allowed."
            ], "fingerprint": "", "commit": "", **selected, "preset": contract}

    def materialize(self, source, destination, tools):
        """Extract the reviewed Git object, never checkout shared development code."""
        destination = Path(destination)
        if any(path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
               for path in (destination, *destination.parents)):
            raise ValueError("Reviewed source destination cannot traverse links.")
        result = subprocess.run(
            [tools["git"], "-C", str(self.root), "archive", "--format=zip", source["commit"],
             "bootstrap", "environment_setup/aifactory"],
            stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=120,
            env=launch_environment({}, tools), shell=False,
        )
        with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
            for item in archive.infolist():
                path = Path(item.filename)
                if (path.is_absolute() or path.drive or ".." in path.parts or "\\" in item.filename
                        or ":" in item.filename or ((item.external_attr >> 16) & 0o170000) == 0o120000):
                    raise ValueError("Published source contains an unsafe archive path.")
            destination.mkdir(parents=True, exist_ok=False)
            archive.extractall(destination)
        return destination / "bootstrap" / self.script.name

    @staticmethod
    def _source_files(tree):
        pending = [tree]
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
                        raise ValueError("Source tree traverses a link")
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name != "__pycache__":
                            pending.append(entry.path)
                    elif entry.is_file(follow_symlinks=False) and not entry.name.endswith(".pyc"):
                        yield Path(entry.path)

    @staticmethod
    def _contract(helper):
        # Read only literal manifest metadata from the authoritative purple
        # helper. Never import it or execute even a purported preview command.
        return SourceReadiness._contract_text(helper.read_text(encoding="utf-8-sig"))

    @staticmethod
    def _contract_text(text):
        tree = ast.parse(text)
        names = {}
        required = {
            "AIF_SIMPLE_MODE_CONTRACT_VERSION", "SIMPLE_MODE_PRESET_NAME", "SIMPLE_MODE_REQUIRED_SOURCE_PATHS",
            "SIMPLE_MODE_RESOURCE_CATALOG", "resource_catalog",
        }
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in required:
                    names[node.targets[0].id] = ast.literal_eval(node.value)
        version = names.get("AIF_SIMPLE_MODE_CONTRACT_VERSION")
        if type(version) is not int or version not in {1, 2}:
            raise ValueError("Unsupported source contract")
        paths = names.get("SIMPLE_MODE_REQUIRED_SOURCE_PATHS")
        if not isinstance(paths, (list, tuple)) or set(paths) != {"bootstrap", "environment_setup/aifactory"}:
            raise ValueError("Unsupported source dependencies")
        name = names.get("SIMPLE_MODE_PRESET_NAME")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", name):
            raise ValueError("Unsupported preset name")
        function = next((node for node in tree.body if isinstance(node, ast.FunctionDef)
                         and node.name == "simple_mode_manifest"), None)
        returned = next((node.value for node in function.body if isinstance(node, ast.Return)), None) if function else None
        if not isinstance(returned, ast.Dict):
            raise ValueError("Manifest missing")
        result = {"contractVersion": version, "preset": name, "requiredSourcePaths": list(paths)}
        fields = {
            "environment", "futureEnvironments", "futureSubscriptionReferences", "limitations",
            "services", "hub", "deploymentIdentityRoles", "policyIdentityRoles",
            "appGateway", "appGatewayInputs", "requiredInputs", "githubVisibilities",
            "stagePrefix", "stages", "repositoryVisibility", "projectResourcesEnvironment",
        }
        for key, value in zip(returned.keys, returned.values):
            if isinstance(key, ast.Constant) and key.value in fields:
                result[key.value] = ast.literal_eval(value)
            if isinstance(key, ast.Constant) and key.value in {"resourceCatalog", "resource_catalog"}:
                if isinstance(value, ast.Name) and value.id in names:
                    result["resourceCatalog"] = names[value.id]
                elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and not value.args and not value.keywords:
                    catalog_function = next((node for node in tree.body if isinstance(node, ast.FunctionDef)
                                             and node.name == value.func.id), None)
                    catalog_return = next((node.value for node in catalog_function.body if isinstance(node, ast.Return)), None) if catalog_function else None
                    if isinstance(catalog_return, ast.Name) and catalog_return.id in names:
                        result["resourceCatalog"] = names[catalog_return.id]
                    else:
                        result["resourceCatalog"] = ast.literal_eval(catalog_return)
                else:
                    result["resourceCatalog"] = ast.literal_eval(value)
        if "resourceCatalog" not in result and "SIMPLE_MODE_RESOURCE_CATALOG" in names:
            result["resourceCatalog"] = names["SIMPLE_MODE_RESOURCE_CATALOG"]
        if result.get("resourceCatalog") is not None:
            result["resourceCatalog"] = validate_catalog(result["resourceCatalog"])
        if not isinstance(result.get("services"), dict) or not isinstance(result.get("hub"), dict):
            raise ValueError("Authoritative service/SKU preset missing")
        return result


def validate_inputs(data):
    if not isinstance(data, dict) or not set(FIELDS).issubset(data) or set(data) - set(FIELDS) - OPTIONAL_FIELDS:
        raise TicketError("Provide only documented Simple Mode fields. Credentials and advanced settings are not accepted.")
    result = {}
    result["aifactory_version"] = release_version.select(data.get("aifactory_version"))["requested_version"]
    result["aifactory_version_input"] = data.get("aifactory_version")
    for name, (limit, pattern) in FIELDS.items():
        value = data[name]
        if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise TicketError(f"Invalid {name}: check its value and length.")
        if pattern and not re.fullmatch(pattern, value):
            raise TicketError(f"Invalid {name}: use the documented format without shell expressions.")
        result[name] = value.lower() if name in {"subscription_id", "tenant_id"} else value
    if result["github_repository"].split("/")[1] in {".", ".."} or result["github_repository"].endswith(".git"):
        raise TicketError("Use a GitHub owner/repository name without a .git suffix.")
    visibility = data.get("github_visibility", "private")
    if not isinstance(visibility, str) or visibility not in {"private", "public"}:
        raise TicketError("github_visibility must be private or public.")
    result["github_visibility"] = visibility
    selected = data.get("project_resources")
    if selected is not None and (
        not isinstance(selected, list) or len(selected) > 50
        or any(not isinstance(value, str) or not re.fullmatch(RESOURCE_ID, value) for value in selected)
        or len(set(selected)) != len(selected)
    ):
        raise TicketError("project_resources must be a list of unique optional resource IDs from the catalog.")
    if "project_resources" in data and selected is None:
        raise TicketError("project_resources must be a list when supplied; omit it to use catalog defaults.")
    result["project_resources"] = selected
    for name in GATEWAY_FIELDS:
        value = data.get(name, "")
        limit = 2048 if name.endswith("secret_id") else 253
        if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise TicketError(f"Invalid {name}. Supply metadata only, never a certificate or secret value.")
        if value:
            if name.endswith("secret_id"):
                pattern = r"https://[a-z0-9-]{3,24}\.vault\.azure\.net/secrets/[A-Za-z0-9-]{1,127}"
            else:
                value = value.lower()
                pattern = r"(?=^.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}"
            if not re.fullmatch(pattern, value):
                raise TicketError(f"Invalid {name}. Use a hostname or Key Vault secret identifier, without credentials or query strings.")
            if name == "app_gateway_hostname" and (value.count(".") < 2 or ".privatelink." in value):
                raise TicketError("app_gateway_hostname must be a custom frontend hostname and domain, not a privatelink hostname.")
        result[name] = value
    return result


def validate_catalog(value):
    if not isinstance(value, dict) or set(value) != {"hub", "common", "project"}:
        raise ValueError("Resource catalog sections are unavailable")
    result = {}
    for section, items in value.items():
        if not isinstance(items, list) or len(items) > 50:
            raise ValueError("Invalid resource catalog")
        seen = set()
        result[section] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Invalid resource catalog item")
            rid = item.get("id")
            if not isinstance(rid, str) or not re.fullmatch(RESOURCE_ID, rid) or rid in seen:
                raise ValueError("Invalid resource catalog identifier")
            seen.add(rid)
            if any(not isinstance(item.get(field), str) or not item[field] or len(item[field]) > limit
                   or any(ord(c) < 32 for c in item[field])
                   for field, limit in (("label", 160), ("description", 2048))):
                raise ValueError("Resource catalog text is unavailable")
            if type(item.get("required")) is not bool or type(item.get("default_selected")) is not bool:
                raise ValueError("Resource catalog flags are unavailable")
            if (item["required"] and not item["default_selected"]) or (section != "project" and not item["required"]):
                raise ValueError("Required catalog resources must be selected and locked")
            dependencies = item.get("dependencies")
            if not isinstance(dependencies, list) or len(dependencies) > 50 or any(
                not isinstance(dep, str) or not re.fullmatch(RESOURCE_ID, dep) for dep in dependencies
            ):
                raise ValueError("Resource catalog dependencies are unavailable")
            result[section].append({key: item[key] for key in (
                "id", "label", "description", "required", "default_selected", "dependencies",
            )})
    if REQUIRED_PROJECT_RESOURCES != {i["id"] for i in result["project"] if i["required"]}:
        raise ValueError("Required project foundations must remain locked")
    known = {item["id"] for items in result.values() for item in items}
    if any(dep not in known for items in result.values() for item in items for dep in item["dependencies"]):
        raise ValueError("Unknown catalog dependency")
    return result


def resource_selection(catalog, requested):
    optional = {item["id"]: item for item in catalog["project"] if not item["required"]}
    selected = [item["id"] for item in optional.values() if item["default_selected"]] if requested is None else requested
    unknown = set(selected) - optional.keys()
    if unknown:
        raise TicketError(
            "project_resources accepts only optional project IDs from the current catalog; "
            "storage, key-vault and managed-identities are always included and must not be supplied."
        )
    selected = [rid for rid in optional if rid in selected]
    project = [item for item in catalog["project"] if item["required"] or item["id"] in selected]
    project_ids = {item["id"] for item in catalog["project"]}
    available = {item["id"] for item in project}
    available.update(item["id"] for section in ("hub", "common") for item in catalog[section] if item["id"] not in project_ids)
    for item in project:
        missing = set(item["dependencies"]) - available
        if missing:
            raise TicketError(f"Resource {item['id']} requires selected dependencies: {', '.join(sorted(missing))}. No resources were silently enabled.")
    return selected, {**catalog, "project": project}


def validate_workspace(value, source_root=None):
    path = Path(value)
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise TicketError("repo_root must be an absolute local directory, not a network share.")
    if not re.fullmatch(r"[A-Za-z0-9 _().:/\\-]+", value) or ".." in path.parts:
        raise TicketError("repo_root contains unsupported characters or parent-directory traversal.")
    if sys.platform == "win32" and (not re.fullmatch(r"[A-Za-z]:\\.*", value) or ":" in value[2:]):
        raise TicketError("repo_root must use a local drive and cannot contain alternate data streams.")
    for part in path.parts[1:]:
        if part.startswith(".") or part.endswith((" ", ".")) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", part):
            raise TicketError("repo_root contains a protected or reserved directory component.")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise TicketError("repo_root cannot traverse symbolic links or directory junctions.")
        if _git_marker_exists(ancestor / ".git"):
            raise TicketError("repo_root must not be inside another Git repository.")
    path = path.resolve()
    protected = [(source_root or accelerator_root()).resolve(), APP_ROOT.resolve()]
    for name in (
        "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA",
        "AZURE_CONFIG_DIR", "GH_CONFIG_DIR", "XDG_CONFIG_HOME",
    ):
        if os.environ.get(name):
            protected.append(Path(os.environ[name]).resolve())
    home = Path.home().resolve()
    if path == home or path == Path(path.anchor):
        raise TicketError("Choose a new factory subdirectory, not your home or drive root.")
    for root in protected:
        if path.is_relative_to(root) or root.is_relative_to(path):
            raise TicketError("repo_root overlaps a protected application, bootstrap or system directory.")
    if path.exists():
        if not path.is_dir() or next(path.iterdir(), None) is not None:
            raise TicketError("repo_root must be new or completely empty. Existing files will not be modified.")
        stat = path.stat()
        state = {"state": "empty", "device": stat.st_dev, "inode": stat.st_ino, "created": stat.st_ctime_ns}
    else:
        state = {"state": "absent"}
    ancestor = next(p for p in (path, *path.parents) if p.exists())
    if not os.access(ancestor, os.W_OK):
        raise TicketError("The API host user cannot write to the workspace parent.")
    return str(path), state


def _git_marker_exists(path):
    return path.exists()


class SimpleModeService:
    def __init__(self, store=None, cli=None, identity=None, source=None, clock=time.time,
                 popen=None, dispatch=None, timeout=8 * 60 * 60):
        self._store = store
        self.cli = cli or ReadOnlyCLI()
        self.clock = clock
        self.identity = identity or AzureTicketIdentity(self.cli, clock=clock)
        self.source = source or SourceReadiness(self.cli)
        self.popen = popen or subprocess.Popen
        self.dispatch = dispatch or self._dispatch
        self.timeout = timeout
        self._ready = False

    @property
    def store(self):
        with _GLOBAL_LOCK:
            if not self._ready:
                self._store = self._store or operations.OperationsStore()
                self._migrate()
                self._ready = True
        return self._store

    def _migrate(self):
        key = str(self._store.db_path.resolve())
        with self._store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS simple_mode_schema(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS simple_mode_plans(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL,
                    payload TEXT NOT NULL, job_id TEXT);
                CREATE TABLE IF NOT EXISTS simple_mode_jobs(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL,
                    payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS simple_mode_one_active
                    ON simple_mode_jobs((1)) WHERE status IN ('queued','running');
            """)
            db.execute("INSERT OR IGNORE INTO simple_mode_schema VALUES(1,?)", (iso(self.clock()),))
            if key not in _INITIALIZED_DATABASES:
                for row in db.execute("SELECT id,payload FROM simple_mode_jobs WHERE status IN ('queued','running')"):
                    job = json.loads(row["payload"])
                    job.update(status="interrupted", stage="interrupted", updated_at=iso(self.clock()),
                               message="API host restarted. Deployment outcome is unknown; inspect local/cloud state before manual reconciliation. No automatic rerun.")
                    job["events"] = (job["events"] + [job["message"]])[-100:]
                    db.execute("UPDATE simple_mode_jobs SET status=?,payload=? WHERE id=?",
                               ("interrupted", json.dumps(job), row["id"]))
                _INITIALIZED_DATABASES.add(key)

    def options(self):
        warnings = list(WARNINGS)
        manifest = self.source.manifest()
        catalog = manifest.get("resourceCatalog", {"hub": [], "common": [], "project": []})
        selected = []
        if manifest.get("contractVersion") == 2 and isinstance(catalog, dict) and catalog.get("project"):
            try:
                catalog = validate_catalog(catalog)
                selected, _ = resource_selection(catalog, None)
            except (ValueError, TicketError):
                catalog = {"hub": [], "common": [], "project": []}
                warnings.append("The installed source resource catalog is invalid; creation is blocked until the updated v2 source is published.")
        else:
            warnings.append("The resource catalog is unavailable or needs Simple Mode v2; creation is blocked until the updated source is installed and published.")
        accounts, login = [], ""
        tools = self.cli.tools()
        for name in ("az", "gh", "git", "bash", "python"):
            if name not in tools:
                warnings.append(f"Missing prerequisite on API host: {name}.")
        try:
            accounts = self.cli.accounts()
            if accounts:
                self.identity()
            else:
                warnings.append("No enabled Azure subscriptions found in the host CLI cache.")
        except TicketError:
            warnings.append("Azure host CLI sign-in/token could not be verified. Sign in separately before preparing.")
        try:
            login, _ = self.cli.github()
        except TicketError:
            warnings.append("GitHub host CLI sign-in could not be verified. Sign in separately before preparing.")
        account = next((a for a in accounts if a["is_default"]), accounts[0] if accounts else {})
        prefix, name = "aif-", "aifaifactory-001"
        defaults = {
            "aifactory_version": release_version.DEFAULT_VERSION,
            "subscription_id": account.get("subscription_id", ""), "tenant_id": account.get("tenant_id", ""),
            "location": "swedencentral", "factory_prefix": prefix,
            "github_repository": f"{login}/{name}" if login else "",
            "team_member_email": account.get("account_name", ""),
            "team_group_name": f"{prefix}prj001-team", "cost_center": "123456",
            "repo_root": str(Path.home() / "Documents" / "AI Factories" / name),
            "github_visibility": "private", "project_resources": selected,
            **{field: "" for field in GATEWAY_FIELDS},
        }
        return {"defaults": defaults,
                "azure_accounts": [{k: v for k, v in a.items() if k != "is_default"} for a in accounts],
                "github_account": login, "regions": list(SUPPORTED_REGIONS),
                "requirements": list(REQUIREMENTS), "warnings": warnings, "script_path": str(SCRIPT),
                "github_visibilities": ["private", "public"], "resource_catalog": catalog}

    def _context(self, data, owner):
        accounts = self.cli.accounts()
        account = next((a for a in accounts if a["subscription_id"] == data["subscription_id"]), None)
        if not account or account["tenant_id"] != data["tenant_id"]:
            raise TicketError("Selected subscription/tenant does not match an enabled host Azure CLI account.", 403)
        scoped = AzureTicketIdentity(ScopedIdentityAuth(self.cli, account), clock=self.clock)()
        if scoped != owner:
            raise TicketError("The selected subscription must use the same authenticated Azure tenant/object identity as the host account.", 403)
        login, scopes = self.cli.github()
        return login, scopes, account

    def prepare(self, inputs):
        data = validate_inputs(inputs)
        blockers = []
        warnings = list(WARNINGS)
        source = self.source.check(data["aifactory_version"])
        manifest = source.get("preset", {})
        catalog = manifest.get("resourceCatalog", {})
        selected_catalog = {"hub": [], "common": [], "project": []}
        if manifest.get("contractVersion") != 2 or not catalog:
            if data["project_resources"]:
                raise TicketError("Project resource selections cannot be validated until the authoritative Simple Mode v2 catalog is available. Refresh options after updating the source.", 409)
            blockers.append("Install and publish Simple Mode capability v2 with the authoritative resource catalog and repository visibility support.")
            data["project_resources"] = data["project_resources"] or []
        else:
            try:
                catalog = validate_catalog(catalog)
            except ValueError:
                raise TicketError("The source resource catalog is invalid. Update the purple source before preparing.", 409) from None
            data["project_resources"], selected_catalog = resource_selection(catalog, data["project_resources"])
        owner = self.identity()
        if data["github_visibility"] == "public":
            warnings.append(PUBLIC_REPOSITORY_WARNING)
        gateway_environment = {}
        gateway_required = any(item["id"] == "application-gateway" and item["required"] for item in selected_catalog["hub"])
        if gateway_required:
            missing = [name for name in GATEWAY_FIELDS if not data[name]]
            if missing:
                blockers.append(
                    "The required private HTTPS Application Gateway needs backend FQDN, frontend hostname and "
                    "a Key Vault TLS certificate secret identifier. Complete: " + ", ".join(missing) + "."
                )
            mapping = manifest.get("appGatewayInputs", {})
            if not mapping and isinstance(manifest.get("requiredInputs"), list):
                entries = manifest["requiredInputs"]
                mapping = {item.get("name"): item.get("environment") for item in entries if isinstance(item, dict)}
            if mapping != GATEWAY_ENV_FIELDS:
                blockers.append("The installed source does not declare the Application Gateway input-to-environment contract. Publish the updated gateway capability before creation.")
            elif not missing:
                gateway_environment = {env: data[field] for field, env in mapping.items()}
            warnings.append("Application Gateway is planned, not deployed or verified; HTTPS requires an existing usable Key Vault certificate reference. No certificate or secret value is accepted.")
        elif any(data[field] for field in GATEWAY_FIELDS):
            blockers.append("Application Gateway inputs are not supported by the installed resource catalog; no supplied gateway configuration will be silently ignored.")
        path_state, target, login = {}, {}, ""
        try:
            data["repo_root"], path_state = validate_workspace(data["repo_root"])
        except TicketError as exc:
            blockers.append(str(exc))
        try:
            login, scopes, _ = self._context(data, owner)
            target = self.cli.repository(data["github_repository"], login, scopes, data["github_visibility"])
            self.cli.roles(data["subscription_id"], owner.split(":")[-1])
        except TicketError as exc:
            blockers.append(str(exc))
        tools = self.cli.tools()
        missing = set(("az", "gh", "git", "bash", "python")) - tools.keys()
        if missing:
            blockers.append("Install these host tools before creation: " + ", ".join(sorted(missing)) + ".")
        if data["location"] not in SUPPORTED_REGIONS:
            blockers.append("Choose a supported Azure region from Simple Mode options.")
        blockers.extend(source["blockers"])
        if source.get("preset") != manifest:
            blockers.append("The source capability changed while preparing. Refresh options and prepare again.")
        environment = {**FIXED_ENV, **{env: data[field] for field, env in ENV_FIELDS.items()}}
        environment.update(
            AIFACTORY_VERSION=data["aifactory_version"], AIFACTORY_VERSION_REVIEWED="1",
            GITHUB_REPOSITORY_VISIBILITY=data["github_visibility"],
            AIF_SIMPLE_PROJECT_RESOURCES_JSON=json.dumps(data["project_resources"], separators=(",", ":")),
            **gateway_environment,
        )
        if source["commit"]:
            environment.update(AIF_SUBMODULE_REF=source["commit"], AIF_SUBMODULE_BRANCH=source["branch"])
        confirmation = str(uuid4())
        execution_script = SCRIPT
        if hasattr(self.source, "materialize"):
            execution_script = self.store.db_path.resolve().parent / "creation-sources" / confirmation / "bootstrap" / SCRIPT.name
        command = subprocess.list2cmdline([
            tools.get("bash", "bash"), str(execution_script), "--non-interactive", "--yes",
            "--repo-root", unix_path(data["repo_root"]),
        ])
        effects = [
            f"Create/use a {data['github_visibility']} GitHub repository https://github.com/{data['github_repository']}; create files in {data['repo_root']}. Existing repository visibility is never changed.",
            "Create/configure an Entra team group, managed identity and OIDC federation; assign Contributor + User Access Administrator to the deployment identity; configure RBAC and policy assignments.",
            "Commit and push generated nonsecret automation/configuration; exclude .env, variables.json, VPN profiles and secrets from commits. Configure GitHub environments/secrets/variables and dispatch common, integrated hub/link, then the selected project resources, waiting for results.",
            f"Deploy billable private Azure resources to existing Dev subscription {data['subscription_id']} in {data['location']}; cost center {data['cost_center']} (default 123456).",
            "Own-mode factory, scale set 001, project 001, private networking and own integrated hub. Stage/Prod are not deployed; future peerable address configuration is not deployed now.",
            "No Azure subscription is created. VPN-client auto-install/configuration is disabled. No password or PAT input is required.",
        ]
        if source.get("preset"):
            effects.append("Authoritative preset: " + source["preset"].get("preset", "unavailable"))
            warnings.extend(source["preset"].get("limitations", []))
        for section, heading in (("hub", "Hub resources:"), ("common", "Common resources:"), ("project", "Project 001 resources (required plus selected optional):")):
            if selected_catalog[section]:
                effects.append(heading)
                effects.extend(
                    f"{item['label']} - {item['description']}" + (" [required]" if item["required"] else " [selected]")
                    for item in selected_catalog[section]
                )
        expires = self.clock() + 600
        preview = {
            "confirmation_id": confirmation, "can_execute": not blockers,
            "summary": f"Create private Azure AI Factory {data['factory_prefix']}001 and Dev project 001; {data['github_visibility']} GitHub repository.",
            "script_path": str(execution_script), "command": command, "environment": environment,
            "effects": effects, "requirements": list(REQUIREMENTS), "warnings": warnings,
            "blockers": blockers, "expires_at": iso(expires),
            "github_visibility": data["github_visibility"], "project_resources": data["project_resources"],
            "resource_catalog": selected_catalog,
            "requested_version": data["aifactory_version"], "branch": source.get("branch", ""),
            "resolved_ref": source.get("commit", ""),
            "aifactory_version": data["aifactory_version_input"],
        }
        payload = {"preview": preview, "inputs": data, "login": login, "workspace": path_state,
                   "target": target, "source": source, "tools": tools, "execution_script": str(execution_script)}
        with self.store._connect() as db:
            db.execute("INSERT INTO simple_mode_plans(id,owner,expires,payload) VALUES(?,?,?,?)",
                       (confirmation, owner, expires, json.dumps(payload)))
        return preview

    def get_job(self, job_id):
        owner = self.identity()
        with self.store._connect() as db:
            row = db.execute("SELECT payload FROM simple_mode_jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        if not row:
            raise TicketError("Creation job not found for the current Azure user.", 404)
        return json.loads(row["payload"])

    def start(self, confirmation_id):
        if not isinstance(confirmation_id, str) or not re.fullmatch(GUID, confirmation_id):
            raise TicketError("A prepared confirmation_id is required.")
        owner = self.identity()
        with _GLOBAL_LOCK:
            with self.store._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM simple_mode_plans WHERE id=? AND owner=?", (confirmation_id, owner)).fetchone()
                if not row:
                    raise TicketError("Confirmation not found for the current Azure user. Prepare again.", 404)
                if row["job_id"]:
                    job = db.execute("SELECT payload FROM simple_mode_jobs WHERE id=?", (row["job_id"],)).fetchone()
                    return json.loads(job["payload"])
                plan = json.loads(row["payload"])
                if row["expires"] <= self.clock() or not plan["preview"]["can_execute"]:
                    raise TicketError("Confirmation expired or has unresolved blockers. Prepare and confirm again.", 409)
                if _LIVE_JOBS or db.execute("SELECT 1 FROM simple_mode_jobs WHERE status IN ('queued','running','interrupted') LIMIT 1").fetchone():
                    raise TicketError("Another creation is active or an interrupted job needs manual reconciliation. Shared Azure CLI state allows only one creation.", 409)
                self._recheck(plan, owner)
                job_id = str(uuid4())
                job = {
                    "id": job_id, "status": "queued", "stage": "queued", "message": "Confirmed creation queued.",
                    "created_at": iso(self.clock()), "updated_at": iso(self.clock()), "exit_code": None,
                    "repository_url": "https://github.com/" + plan["inputs"]["github_repository"],
                    "repo_root": plan["inputs"]["repo_root"], "events": ["Confirmed creation queued."],
                }
                db.execute("INSERT INTO simple_mode_jobs VALUES(?,?,?,?)", (job_id, owner, "queued", json.dumps(job)))
                db.execute("UPDATE simple_mode_plans SET job_id=? WHERE id=?", (job_id, confirmation_id))
                _LIVE_JOBS.add(job_id)
            try:
                self.dispatch(lambda: self._work(job_id, plan, owner))
            except RuntimeError:
                _LIVE_JOBS.discard(job_id)
                self._update(job_id, status="failed", stage="failed", message="Could not start the creation worker. No automatic retry.")
                job.update(status="failed", stage="failed", message="Could not start the creation worker. No automatic retry.")
            return job

    def _recheck(self, plan, owner):
        if self.identity() != owner:
            raise TicketError("Azure identity changed after confirmation. Prepare again.", 409)
        data = plan["inputs"]
        login, scopes, _ = self._context(data, owner)
        path, state = validate_workspace(data["repo_root"])
        source = self.source.check(data.get("aifactory_version"))
        if login != plan["login"] or path != data["repo_root"] or state != plan["workspace"]:
            raise TicketError("Identity or local destination changed after preview. Prepare again.", 409)
        if source["blockers"] or source != plan["source"] or self.cli.tools() != plan["tools"]:
            raise TicketError("Bootstrap source, publication or host tools changed after preview. Prepare again.", 409)
        if (source.get("preset", {}).get("contractVersion") != 2 or "github_visibility" not in data
                or not isinstance(data.get("project_resources"), list)):
            raise TicketError("The confirmation predates the current resource/visibility contract. Prepare again.", 409)
        selected_version = {
            "requested_version": data["aifactory_version"], "branch": source["branch"],
            "resolved_ref": source["commit"],
        }
        expected_version = release_version.environment(selected_version)
        if (any(plan["preview"]["environment"].get(key) != value for key, value in expected_version.items())
                or any(plan["preview"].get(key) != value for key, value in selected_version.items())):
            raise TicketError("Reviewed AI Factory version changed after confirmation. Prepare again.", 409)
        if plan["preview"].get("aifactory_version") != data.get("aifactory_version_input"):
            raise TicketError("Reviewed AI Factory version input changed after confirmation. Prepare again.", 409)
        if self.cli.repository(data["github_repository"], login, scopes, data["github_visibility"]) != plan["target"]:
            raise TicketError("GitHub destination changed after preview. Prepare again.", 409)
        self.cli.roles(data["subscription_id"], owner.split(":")[-1])

    @staticmethod
    def _dispatch(action):
        threading.Thread(target=action, daemon=False, name="simple-mode-bootstrap").start()

    def _update(self, job_id, **changes):
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM simple_mode_jobs WHERE id=?", (job_id,)).fetchone()
            job = json.loads(row["payload"])
            job.update(changes, updated_at=iso(self.clock()))
            if changes.get("message") and (not job["events"] or job["events"][-1] != changes["message"]):
                job["events"] = (job["events"] + [changes["message"]])[-100:]
            db.execute("UPDATE simple_mode_jobs SET status=?,payload=? WHERE id=?",
                       (job["status"], json.dumps(job), job_id))

    def _work(self, job_id, plan, owner):
        process = None
        timer = None
        timed_out = threading.Event()
        reported_completion = False
        source_directory = None
        try:
            self._recheck(plan, owner)
            script = SCRIPT
            if hasattr(self.source, "materialize"):
                source_directory = Path(plan["execution_script"]).parent.parent
                script = self.source.materialize(plan["source"], source_directory, plan["tools"])
            self._update(job_id, status="running", stage="preflight", message=STAGES["preflight"])
            process = self.popen(
                [plan["tools"]["bash"], str(script), "--non-interactive", "--yes",
                 "--repo-root", unix_path(plan["inputs"]["repo_root"])],
                shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                cwd=str(script.parent), env=launch_environment(plan["preview"]["environment"], plan["tools"]),
                **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}),
            )

            def terminate_owned():
                if process.poll() is not None:
                    return
                timed_out.set()
                self._stop_owned_process(process)

            timer = threading.Timer(self.timeout, terminate_owned)
            timer.daemon = True
            timer.start()
            # Consume bounded chunks and accept only complete protocol lines.
            # Raw stdout (including errors, passwords, PATs, JWTs) is discarded.
            while True:
                line = process.stdout.readline(4097)
                if not line:
                    break
                if len(line) > 4096 or not line.endswith("\n"):
                    while line and not line.endswith("\n"):
                        line = process.stdout.readline(4097)
                    continue
                stage = output_stage(line)
                if stage:
                    reported_completion = stage == "completed"
                    self._update(job_id, stage=stage, message=STAGES[stage])
            code = process.wait()
            success = code == 0 and reported_completion and not timed_out.is_set()
            self._update(
                job_id, status="succeeded" if success else "failed", stage="completed" if success else "failed",
                exit_code=code,
                message="AI Factory creation completed." if success else (
                    "Creation exceeded the eight-hour limit; its owned process tree was stopped. Inspect partial resources; no automatic retry."
                    if timed_out.is_set() else f"Bootstrap did not report a completed deployment (exit code {code}). Inspect partial resources and GitHub workflow runs; no automatic retry."
                ),
            )
        except (TicketError, OSError, subprocess.SubprocessError, sqlite3.Error, ValueError, RuntimeError):
            if process and process.poll() is None:
                self._stop_owned_process(process)
            self._update(job_id, status="failed", stage="failed",
                         message="Creation could not complete safely. Inspect host prerequisites and any partial deployment; prepare again only after reconciliation. No automatic retry.")
        finally:
            if timer:
                timer.cancel()
            if process and process.stdout:
                process.stdout.close()
            if source_directory and source_directory.is_dir():
                shutil.rmtree(source_directory)
            with _GLOBAL_LOCK:
                _LIVE_JOBS.discard(job_id)

    def _stop_owned_process(self, process):
        if process.poll() is not None:
            return
        try:
            if sys.platform == "win32":
                # Only the still-live child created by this worker is targeted.
                self.cli.runner(
                    [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
                     "/PID", str(process.pid), "/T", "/F"],
                    shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            else:
                import signal
                os.killpg(process.pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if process.poll() is None:
                process.kill()
