"""Opt-in, target-bound project deployment for the interactive root launchers."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


CONTRACT = "AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1"
VERSION_CONTRACT = "AIFACTORY_VERSION_CONTRACT=1"
_version_spec = importlib.util.spec_from_file_location("aifactory_release_version", Path(__file__).with_name("release_version.py"))
release_version = importlib.util.module_from_spec(_version_spec)
_version_spec.loader.exec_module(release_version)
GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
ADO_PIPELINE = "aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/infra-project-genai.yaml"
ADO_CONFIG_STEP = "aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/jobs/job-0-reviewed-project-config.yaml"
FILES = {
    "gha": (".github/workflows/infra-project.yml", ".github/workflows/infra-project-phase.yml"),
    "ado": (ADO_PIPELINE, ADO_CONFIG_STEP),
}
RUNTIME_CONFIG = "aifactory/.reviewed-project-config.json"


def validate_config(document, project, target):
    if not re.fullmatch(r"[0-9]{3}", project) or project == "000" or target not in ("dev", "stage", "prod"):
        raise ValueError("A three-digit project and exact dev/stage/prod target are required.")
    if not isinstance(document, dict):
        raise ValueError("Selected project JSON must be an object.")
    section = "dev" if target == "dev" else "stage_prod"
    values = document.get(section)
    if not isinstance(values, dict):
        raise ValueError(f"Selected project JSON has no {section} object; Dev fallback is forbidden.")
    for name in ("dev", section):
        if str((document.get(name) or {}).get("project_number_000", "")).zfill(3) != project:
            raise ValueError("Selected configuration project identity does not match the reviewed project.")
    subscription = str(values.get({"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}[target], ""))
    tenant = str(values.get("tenantId", ""))
    if not re.fullmatch(GUID, subscription) or not re.fullmatch(GUID, tenant):
        raise ValueError("Exact target subscription and tenant are required; no Dev fallback is permitted.")
    if any(str(values.get(key, "")).lower() in ("true", "1", "yes") for key in (
        "deleteAllForProject", "deleteAllServicesForProject",
    )):
        raise ValueError("A project promotion cannot use deletion configuration.")
    return {"project": project, "target": target, "subscription": subscription.lower(),
            "tenant": tenant.lower(), "values": values}


def canonical_json(document):
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_config(path, root, project, target):
    path = Path(path)
    if any(item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction())
           for item in (path, *path.parents)):
        raise ValueError("Selected configuration may not traverse links.")
    path = path.resolve()
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Selected configuration must be a bounded file.")
    if path.suffix != ".dpapi":
        if not path.is_relative_to(root / "aifactory"):
            raise ValueError("Selected JSON must be inside this factory.")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    if sys.platform != "win32":
        raise ValueError("Derived encrypted configuration requires Windows current-user DPAPI.")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    raw = path.read_bytes()
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.c_void_p))
    result = Blob()
    if not crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError("Cannot decrypt the reviewed configuration as the current Windows user.")
    try:
        envelope = json.loads(ctypes.string_at(result.data, result.size).decode("utf-8"))
    finally:
        ctypes.memset(result.data, 0, result.size)
        kernel.LocalFree(result.data)
    if (envelope.get("schema") != 1 or envelope.get("project") != project or envelope.get("target") != target
            or os.path.normcase(str(Path(envelope.get("folder", "")).resolve())) != os.path.normcase(str(root / "aifactory"))):
        raise ValueError("Encrypted configuration belongs to a different factory/project/target.")
    return envelope["document"]


def run_request(branch, config, selected):
    values = selected["values"]
    settings = {key: str(values.get(key, default)).lower() if isinstance(default, bool)
                else str(values.get(key, default)) for key, default in {
                    "runNetworkingVar": True, "BYO_subnets": False, "useSelfHostedBuildAgent": False,
                    "adminVMBuildAgentPool": "", "adminVMBuildAgentName": "",
                    "admin_locationSuffix": "", "admin_commonResourceSuffix": "",
                }.items()}
    return {
        "resources": {"repositories": {"self": {"refName": "refs/heads/" + branch}}},
        "templateParameters": {
            "configFile": RUNTIME_CONFIG, "useJsonConfigOverride": True,
            "runnerSelection": "from-config", "deploymentTarget": selected["target"],
            "deploymentProjectNumber": selected["project"],
            "deploymentConfigHash": hashlib.sha256(config.encode("utf-8")).hexdigest(),
            "deploymentSettings": settings,
        },
        "variables": {"AIFACTORY_CONFIG_JSON": {"value": config, "isSecret": True}},
        "stagesToSkip": [
            stage for environment, stage in (
                ("dev", "Dev_GenAI_Project"), ("stage", "Stage_GenAI_Project"), ("prod", "Prod_GenAI_Project"),
            ) if environment != selected["target"]
        ],
    }


def correlated_run(runs, title, commit):
    matches = [row for row in runs if row.get("displayTitle") == title
               and row.get("headSha") == commit and row.get("event") == "workflow_dispatch"]
    if len(matches) > 1:
        raise ValueError("Multiple runs have the deployment correlation ID; refusing to watch an unrelated run.")
    if not matches:
        return None
    value = matches[0].get("databaseId")
    if type(value) is not int or value <= 0:
        raise ValueError("GitHub returned an invalid correlated run ID.")
    return str(value)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Deployment:
    def __init__(self, route, root, state_dir, runner=None, prompt=input, sleep=time.sleep):
        self.route, self.root, self.state_dir = route, Path(root).resolve(), Path(state_dir).resolve()
        self.runner = runner or subprocess.run
        self.prompt, self.sleep = prompt, sleep
        self.environment = dict(os.environ)
        self.opener = build_opener(NoRedirect)

    def command(self, argv, *, capture=False, data=None, check=True):
        command = list(argv)
        if command[0] == "az" and sys.platform == "win32":
            launcher = shutil.which("az.cmd") or shutil.which("az")
            if not launcher:
                raise ValueError("Azure CLI is unavailable.")
            path = Path(launcher)
            if path.suffix.lower() in (".cmd", ".bat"):
                python = path.parent.parent / "python.exe"
                if not python.is_file():
                    raise ValueError("Azure CLI bundled Python is unavailable; refusing a batch-shell fallback.")
                command = [str(python), "-IBm", "azure.cli", *command[1:]]
        result = self.runner(
            command, cwd=str(self.root), env=self.environment, shell=False,
            text=True, encoding="utf-8", errors="replace", input=data,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
        if check and result.returncode:
            raise ValueError(f"{argv[0]} {argv[1]} failed (exit {result.returncode}); reconcile any partial changes.")
        return result.stdout.strip() if capture else result.returncode

    def read_json(self, argv):
        return json.loads(self.command(argv, capture=True))

    def ado(self, method, endpoint, data=None):
        token = self.read_json([
            "az", "account", "get-access-token", "--tenant", self.selected["tenant"],
            "--resource", "https://app.vssps.visualstudio.com/", "--output", "json",
        ])
        if token.get("tenant", "").lower() != self.selected["tenant"] or not token.get("accessToken"):
            raise ValueError("Azure DevOps token tenant does not match the reviewed target.")
        request = Request(
            self.ado_base + endpoint, method=method,
            data=json.dumps(data).encode("utf-8") if data is not None else None,
            headers={"Authorization": "Bearer " + token["accessToken"], "Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=60) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("Azure DevOps response exceeds the supported size.")
            return json.loads(raw)
        except (HTTPError, URLError):
            raise ValueError("Azure DevOps request failed; no redirect or credential fallback was permitted.") from None

    def prepare(self, project, target, config_path):
        if not (self.root / ".git").exists() or not (self.root / "aifactory").is_dir():
            raise ValueError("Selected root must be the consumer Git repository immediately above aifactory.")
        document = load_config(config_path, self.root, project, target)
        path = Path(config_path).resolve()
        self.selected = validate_config(document, project, target)
        self.config = canonical_json(document)
        self.config_path = path
        if self.route == "ado":
            organization_tenant = str(document.get("dev", {}).get("azureDevOpsTenantId", "")).strip()
            if organization_tenant and organization_tenant.lower() != self.selected["tenant"]:
                raise ValueError("Cross-tenant Azure DevOps organization authentication is not supported by this reviewed contract.")
        self.templates = {}
        for relative in FILES[self.route]:
            installed = self.root / relative
            text = installed.read_text(encoding="utf-8-sig")
            if CONTRACT not in text:
                raise ValueError(f"Install the reviewed target-selection template before deployment: {relative}")
            self.templates[relative] = installed.read_bytes()
        account = self.read_json(["az", "account", "show", "--subscription", self.selected["subscription"], "--output", "json"])
        if account.get("id", "").lower() != self.selected["subscription"] or account.get("tenantId", "").lower() != self.selected["tenant"]:
            raise ValueError("The authenticated Azure target differs from the selected configuration.")
        self.account = {key: account.get(key) for key in ("id", "tenantId", "user")}
        self.origin = self.command(["git", "remote", "get-url", "origin"], capture=True)
        if self.route == "gha":
            match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", self.origin)
            if not match:
                raise ValueError("A credential-free GitHub consumer origin is required.")
            self.repository = match[1]
            configured = str(self.selected["values"].get("GITHUB_NEW_REPO", "")).removeprefix("https://github.com/").removesuffix(".git")
            if configured.lower() != self.repository.lower():
                raise ValueError("Selected project GitHub destination differs from the consumer origin.")
            self.command(["gh", "auth", "status"])
            self.github_identity = self.read_json(["gh", "api", "user"]).get("id")
            if type(self.github_identity) is not int:
                raise ValueError("GitHub authenticated identity could not be bound.")
        else:
            parsed = urlsplit(self.origin)
            match = re.fullmatch(r"/([^/]+)/([^/]+)/_git/([^/]+)", parsed.path.rstrip("/"))
            if parsed.scheme != "https" or parsed.hostname != "dev.azure.com" or parsed.username or parsed.password or not match:
                raise ValueError("A credential-free dev.azure.com organization/project/_git/repository origin is required.")
            org, project_name, repository = (unquote(item) for item in match.groups())
            if any(not re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", value) for value in (org, project_name, repository)):
                raise ValueError("Unsupported Azure DevOps destination identifiers.")
            self.repository = repository
            self.ado_base = "https://dev.azure.com/" + quote(org, safe="") + "/" + quote(project_name, safe="") + "/_apis"
        print(f"Reviewed project {project} -> {target}; subscription {self.selected['subscription']}; tenant {self.selected['tenant']}", flush=True)

    def update(self, project_only=False):
        version = release_version.select(saved=release_version.saved_version(self.root), environ=self.environment)
        if not version["resolved_ref"]:
            raise ValueError("Resolve and review an exact AI Factory version before running the launcher.")
        if project_only:
            if version["requested_version"] != release_version.saved_version(self.root):
                raise ValueError("Selecting another version requires Patch or a prior upgrade.")
            current = self.command(["git", "-C", "azure-enterprise-scale-ml", "rev-parse", "HEAD"], capture=True)
            if current != version["resolved_ref"]:
                raise ValueError("Installed AI Factory commit changed after review.")
            print("Project-only mode: no checkout, pull, template update, commit or push.", flush=True)
            return
        branch = "main"
        templates = {}
        for relative in FILES[self.route]:
            if self.route == "gha":
                source_path = "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/" + Path(relative).name
            else:
                source_path = ("environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/"
                               + relative.split("/esml-infra-project/", 1)[1])
            content = self.command(["git", "-C", "azure-enterprise-scale-ml", "show",
                                    version["resolved_ref"] + ":" + source_path], capture=True)
            if CONTRACT not in content:
                raise ValueError("Selected published project pipeline lacks the reviewed contract; no fallback.")
            templates[relative] = (content + "\n").encode("utf-8")
        self.templates = templates
        protected = {}
        for relative in (".env", "aifactory/variables.json",
                         "aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"):
            path = self.root / relative
            protected[relative] = path.read_bytes() if path.is_file() else None
        selected_path = getattr(self, "config_path", None)
        selected_exclusion = []
        if selected_path and selected_path.is_relative_to(self.root):
            relative = selected_path.relative_to(self.root).as_posix()
            protected[relative] = selected_path.read_bytes()
            selected_exclusion = [":(exclude)" + relative]
        bootstrap = "03-GH-bootstrap-files-no-env-overwrite.sh" if self.route == "gha" else "03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"
        try:
            self.command(["git", "stash", "push", "--include-untracked", "--message", "Before reviewed project deployment", "--", ".",
                          ":(exclude).env", ":(exclude)aifactory/variables.json", ":(exclude)aifactory/config-wizard/**",
                          ":(exclude)aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml", *selected_exclusion])
            self.command(["git", "checkout", branch])
            self.command(["git", "pull", "--ff-only", "origin", branch])
            self.command(["git", "submodule", "update", "--init", "--recursive"])
            self.command(["git", "-C", "azure-enterprise-scale-ml", "fetch", "origin", version["resolved_ref"]])
            self.command(["git", "-C", "azure-enterprise-scale-ml", "checkout", "--detach", version["resolved_ref"]])
            current = self.command(["git", "-C", "azure-enterprise-scale-ml", "rev-parse", "HEAD"], capture=True)
            if current != version["resolved_ref"]:
                raise ValueError("AI Factory checkout differs from the exact reviewed version.")
            self.command(["bash", "azure-enterprise-scale-ml/00-start.sh"], data="g\n" if self.route == "gha" else "a\n")
            self.command(["bash", "01-aif-copy-aifactory-templates.sh"])
            self.command(["bash", bootstrap])
            release_version.save(self.root, version)
        finally:
            for relative, content in protected.items():
                path = self.root / relative
                if content is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                elif path.is_file():
                    path.unlink()
            for relative, content in self.templates.items():
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        # Restore the stable reviewed entry point and helper, not the fetched replacements.
        launcher = ("GH" if self.route == "gha" else "ADO") + "-update-aifactory-and-run-project.sh"
        shutil.copyfile(self.state_dir / launcher, self.root / launcher)
        helper = self.root / "lib" / "project_deployment.py"
        helper.parent.mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__), helper)
        for name in ("release_version.py", "release_version.sh"):
            shutil.copyfile(Path(__file__).with_name(name), helper.with_name(name))
        paths = [*FILES[self.route], launcher, "lib/project_deployment.py", "lib/release_version.py",
                 "lib/release_version.sh", "azure-enterprise-scale-ml"]
        alias = "GHA-update-aifactory-and-run-project.sh"
        if self.route == "gha" and (self.state_dir / alias).is_file():
            shutil.copyfile(self.state_dir / alias, self.root / alias)
            paths.append(alias)
        self.command(["git", "add", "--", *paths])
        staged = self.command(["git", "diff", "--cached", "--name-only"], capture=True).splitlines()
        if any(path not in paths for path in staged):
            raise ValueError("Unrelated files are staged. Review the index manually; no commit or push was performed.")
        if staged:
            answer = self.prompt("Commit and push reviewed deployment templates (configuration excluded)? [y/N]: ")
            if answer.strip().lower() not in ("y", "yes"):
                raise ValueError("Commit declined. No pipeline was dispatched; local changes remain for review.")
            self.command(["git", "commit", "-m", "Update reviewed AI Factory project deployment templates",
                          "-m", "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"])
            self.command(["git", "push", "origin", branch])

    def github(self):
        correlation = str(uuid4())
        secret = "AIFACTORY_PROJECT_" + correlation.replace("-", "").upper()
        title = f"infra-project {self.selected['target']} [{correlation}]"
        commit = self.command(["git", "rev-parse", "HEAD"], capture=True)
        remote_head = self.command(["git", "ls-remote", "--exit-code", "origin", "refs/heads/main"], capture=True).split()
        if len(remote_head) != 2 or remote_head[0] != commit:
            raise ValueError("Local reviewed HEAD is not the published main branch; no secret or dispatch was created.")
        self.command(["gh", "secret", "set", secret, "--repo", self.repository, "--env", self.selected["target"]], data=self.config)
        self.command([
            "gh", "workflow", "run", "infra-project.yml", "--repo", self.repository, "--ref", "main",
            "--raw-field", "environment=" + self.selected["target"], "--raw-field", "config_file=" + RUNTIME_CONFIG,
            "--raw-field", "config_secret=" + secret, "--raw-field", "deployment_id=" + correlation,
            "--raw-field", "project_number=" + self.selected["project"],
            "--raw-field", "config_hash=" + hashlib.sha256(self.config.encode("utf-8")).hexdigest(),
            "--raw-field", "runner_selection=from-config",
        ])
        run_id = None
        for _ in range(60):
            runs = self.read_json(["gh", "run", "list", "--repo", self.repository, "--workflow", "infra-project.yml",
                                  "--branch", "main", "--event", "workflow_dispatch", "--limit", "100",
                                  "--json", "databaseId,displayTitle,headSha,event"])
            run_id = correlated_run(runs, title, commit)
            if run_id:
                break
            self.sleep(2)
        if not run_id:
            raise ValueError(f"Dispatch correlation {correlation} was not resolved; do not retry. The run-specific secret is retained for reconciliation.")
        print(f"Watching exact GitHub run {run_id}, correlation {correlation}", flush=True)
        self.command(["gh", "run", "watch", run_id, "--repo", self.repository, "--exit-status"], check=False)
        result = self.read_json(["gh", "run", "view", run_id, "--repo", self.repository, "--json", "status,conclusion"])
        if result.get("status") != "completed":
            raise ValueError("GitHub run completion is unverified; preserve the run-specific secret and reconcile manually.")
        self.command(["gh", "secret", "delete", secret, "--repo", self.repository, "--env", self.selected["target"]])
        if result.get("conclusion") != "success":
            raise ValueError("The selected GitHub project run failed or was cancelled.")

    def azure_devops(self):
        definitions = self.ado("GET", "/build/definitions?includeAllProperties=true&api-version=7.1&%24top=1000").get("value", [])
        if len(definitions) >= 1000:
            raise ValueError("Pipeline inventory is too large to establish an unambiguous definition safely.")
        matches = [row for row in definitions
                   if str(row.get("repository", {}).get("name", "")).lower() == self.repository.lower()
                   and str(row.get("process", {}).get("yamlFilename", "")).replace("\\", "/").lstrip("/").lower() == ADO_PIPELINE.lower()
                   and row.get("queueStatus", "enabled") == "enabled"]
        if len(matches) != 1:
            raise ValueError("The exact repository/YAML Azure DevOps pipeline is missing or ambiguous.")
        pipeline_id = matches[0].get("id")
        if type(pipeline_id) is not int or pipeline_id <= 0:
            raise ValueError("Invalid Azure DevOps pipeline identifier.")
        request = run_request("main", self.config, self.selected)
        run = self.ado("POST", f"/pipelines/{pipeline_id}/runs?api-version=7.1", request)
        run_id = run.get("id")
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("Azure DevOps did not return the exact queued run ID; do not retry.")
        print(f"Watching exact Azure DevOps pipeline {pipeline_id} run {run_id}", flush=True)
        while True:
            result = self.ado("GET", f"/pipelines/{pipeline_id}/runs/{run_id}?api-version=7.1")
            if result.get("state") == "completed":
                break
            if result.get("state") not in ("inProgress", "canceling", "unknown"):
                raise ValueError("Azure DevOps returned an unrecognized run state.")
            print(f"Azure DevOps run {run_id}: {result['state']}", flush=True)
            self.sleep(15)
        if result.get("result") != "succeeded":
            raise ValueError("The selected Azure DevOps project run failed or was cancelled.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", required=True, choices=("gha", "ado"))
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()
    try:
        required = ("AIFACTORY_PROJECT_NUMBER", "AIFACTORY_TARGET_ENVIRONMENT", "AIFACTORY_PROJECT_CONFIG", "AIFACTORY_REPO_ROOT")
        if not all(os.environ.get(name) for name in required):
            raise ValueError("All reviewed project, target, config and repository inputs are required.")
        if args.route == "ado" and (os.environ.get("ADO_BRANCH", "main") != "main" or os.environ.get("ADO_AUTH_METHOD", "aad") != "aad"):
            raise ValueError("The reviewed ADO contract supports main and explicit same-tenant Entra authentication only.")
        deployment = Deployment(args.route, os.environ["AIFACTORY_REPO_ROOT"], args.state_dir)
        deployment.prepare(os.environ["AIFACTORY_PROJECT_NUMBER"], os.environ["AIFACTORY_TARGET_ENVIRONMENT"],
                           os.environ["AIFACTORY_PROJECT_CONFIG"])
        deployment.update(os.environ.get("AIFACTORY_PROJECT_ONLY", "false").lower() in ("true", "yes", "1"))
        if deployment.command(["git", "remote", "get-url", "origin"], capture=True) != deployment.origin:
            raise ValueError("Repository origin changed during refresh.")
        account = deployment.read_json(["az", "account", "show", "--subscription", deployment.selected["subscription"], "--output", "json"])
        if {key: account.get(key) for key in ("id", "tenantId", "user")} != deployment.account:
            raise ValueError("Azure identity/target changed during refresh.")
        if args.route == "gha":
            if deployment.read_json(["gh", "api", "user"]).get("id") != deployment.github_identity:
                raise ValueError("GitHub authenticated identity changed during refresh.")
            deployment.github()
        else:
            deployment.azure_devops()
        print("Selected project pipeline completed successfully. Refresh Azure inventory to verify Active.", flush=True)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
