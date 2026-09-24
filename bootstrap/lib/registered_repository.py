"""Reviewed repository initialization without staging or replacing a saved draft."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

import factory_enrollment as enrollment
import registered_prerequisites as prerequisites
import release_version


SHARED_URL = "https://github.com/jostrm/azure-enterprise-scale-ml"
SHARED_PATH = "azure-enterprise-scale-ml"
LOCK_REF = "refs/heads/aifactory-initializer-lock"
require = enrollment.require


class Repository:
    def __init__(self, target, provider, config, command_runner=None):
        self.target, self.provider, self.config = target, provider, config
        self.runner = command_runner or enrollment._run_cli
        self.cloud = enrollment.Cloud({"target": target, "ado_tenant_id": config.get("ado_tenant_id") or target["tenant_id"]},
                                      command_runner=self.runner)

    def git(self, root, *args, data=None, environment=None, missing=False, raw=False):
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
        if environment:
            env.update(environment)
        result = self.runner(["git", "-c", "core.hooksPath=NUL" if os.name == "nt" else "core.hooksPath=/dev/null",
                              "-C", str(root), *args], input=data, capture_output=True, check=False,
                             timeout=180, shell=False, env=env)
        if missing and result.returncode:
            return None
        require(result.returncode == 0, "repository-command-failed")
        if raw:
            require(isinstance(result.stdout, bytes), "repository-raw-output-required")
            return result.stdout
        return result.stdout.decode("utf-8").strip() if isinstance(result.stdout, bytes) else result.stdout.strip()

    def source_assets(self, sha):
        request = Request("https://api.github.com/repos/jostrm/azure-enterprise-scale-ml/git/trees/" + sha + "?recursive=1",
                          headers={"Accept": "application/vnd.github+json", "User-Agent": "AI-Factory-reviewed-bootstrap"})
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
        except (OSError, TimeoutError):
            raise enrollment.EnrollmentError("published-source-inventory-unavailable") from None
        require(len(raw) <= 8 * 1024 * 1024, "published-source-inventory-too-large")
        tree = enrollment.parse_json(raw)
        require(tree.get("sha") == sha and tree.get("truncated") is False, "complete-published-source-tree-required")
        files = {item["path"]: item for item in tree["tree"] if item.get("type") == "blob"}
        single_writer = self.config.get("coordination_mode") == "single-writer"
        required = {"bootstrap/templates/factory-lifecycle-" + self.provider + ".yml",
                    "bootstrap/templates/hub_private_probe.py", "bootstrap/lib/common_network_preservation.py",
                    "bootstrap/lib/hub_private_transition.py"}
        helpers = ("lib/common_network_preservation.py", "lib/hub_private_transition.py", "templates/hub_private_probe.py")
        if single_writer:
            helpers = ("lib/common_network_preservation.py", "lib/provider_repository_state.py",
                       "lib/factory_enrollment.py", "lib/factory_lifecycle.py")
            required = {"bootstrap/" + relative for relative in helpers} | {
                "bootstrap/templates/factory-lifecycle-single-writer-" + self.provider + ".yml"}
        require(required <= files.keys(), "selected-published-source-lacks-prefix-bootstrap")
        for relative in helpers:
            content = (Path(__file__).parent.parent / relative).read_bytes()
            expected = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            require(files["bootstrap/" + relative]["sha"] == expected, "published-prefix-bootstrap-helper-mismatch:" + relative)
        return {name: files[name]["sha"] for name in sorted(required)}

    def discover(self):
        if self.provider == "gha":
            status, _, value = self.cloud.gh("GET", "repos/" + self.config["github_repository"], allowed=(200, 404))
            return value if status == 200 else None
        url = self.config["ado_organization"].rstrip("/") + "/" + quote(self.config["ado_project"], safe="")
        status, _, value = self.cloud.http("GET", url + "/_apis/git/repositories/" +
                                          quote(self.config["ado_repository"], safe="") + "?api-version=7.1",
                                          enrollment.ADO_AUDIENCE,
                                          tenant=self.config.get("ado_tenant_id") or self.target["tenant_id"],
                                          allowed=(200, 404))
        return value if status == 200 else None

    def private_project(self):
        require(self.provider == "ado", "ado-project-verification-required")
        url = self.config["ado_organization"].rstrip("/") + "/_apis/projects/" + quote(self.config["ado_project"], safe="")
        _, _, project = self.cloud.http("GET", url + "?api-version=7.1", enrollment.ADO_AUDIENCE,
                                       tenant=self.config.get("ado_tenant_id") or self.target["tenant_id"])
        require(project.get("visibility") == "private"
                and str(project.get("name", "")).casefold() == self.config["ado_project"].casefold(),
                "single-writer-private-repository-required")
        return {"id": project.get("id"), "name": project["name"], "visibility": "private"}

    def create(self):
        self.cloud.read_only = False
        if self.provider == "gha":
            owner, name = self.config["github_repository"].split("/")
            user = enrollment.parse_json(self.cloud.command(["gh", "api", "--hostname", "github.com", "user"]))
            endpoint = "user/repos" if user["login"].casefold() == owner.casefold() else "orgs/" + owner + "/repos"
            return enrollment.parse_json(self.cloud.command(
                ["gh", "api", "--hostname", "github.com", "--method", "POST", endpoint, "--input", "-"],
                enrollment.canonical({"name": name, "private": self.config.get("github_visibility", "private") == "private",
                                      "auto_init": False})))
        url = self.config["ado_organization"].rstrip("/") + "/" + quote(self.config["ado_project"], safe="")
        return self.cloud.http("POST", url + "/_apis/git/repositories?api-version=7.1", enrollment.ADO_AUDIENCE,
                               {"name": self.config["ado_repository"]},
                               tenant=self.config.get("ado_tenant_id") or self.target["tenant_id"], allowed=(201,))[2]

    def set_initial_default_branch(self):
        if self.provider == "gha":
            self.cloud.command(["gh", "api", "--hostname", "github.com", "--method", "PATCH",
                                "repos/" + self.config["github_repository"], "--input", "-"],
                               enrollment.canonical({"default_branch": "main"}))
        else:
            self.cloud.command(["az", "repos", "update", "--organization", self.config["ado_organization"],
                                "--project", self.config["ado_project"], "--repository", self.config["ado_repository"],
                                "--default-branch", "refs/heads/main", "--only-show-errors", "--output", "none"])
        value = self.discover()
        require((value.get("default_branch") if self.provider == "gha" else value.get("defaultBranch"))
                == ("main" if self.provider == "gha" else "refs/heads/main"), "repository-default-branch-not-verified")

    def environment(self, name):
        status, _, value = self.cloud.gh(
            "GET", "repos/" + self.config["github_repository"] + "/environments/" + quote(name, safe=""),
            allowed=(200, 404))
        return value if status == 200 else None

    def ensure_environment(self, name, expected):
        current = self.environment(name)
        if expected is not None:
            require(current == expected, "reviewed-github-environment-changed")
        if current is not None:
            return current
        repository = self.discover()
        require(repository and isinstance(repository.get("node_id"), str), "github-repository-node-required")
        # GraphQL creates or returns unchanged; REST PUT can overwrite protection rules.
        mutation = ("mutation($repository:ID!,$name:String!){createEnvironment(input:"
                    "{repositoryId:$repository,name:$name}){environment{id name}}}")
        self.cloud.read_only = False
        result = enrollment.parse_json(self.cloud.command(
            ["gh", "api", "--hostname", "github.com", "--method", "POST", "graphql", "--input", "-"],
            enrollment.canonical({"query": mutation, "variables": {
                "repository": repository["node_id"], "name": name}})))
        require(not result.get("errors"), "github-environment-create-not-verified")
        created = result.get("data", {}).get("createEnvironment", {}).get("environment") or {}
        actual = self.environment(name)
        require(actual and actual.get("name") == name and created.get("name") == name
                and actual.get("node_id") == created.get("id"), "github-environment-create-not-verified")
        return actual

    def pipeline(self, repository):
        if self.provider != "ado" or repository is None:
            return None
        api = self.config["ado_organization"].rstrip("/") + "/" + quote(self.config["ado_project"], safe="") + "/_apis"
        _, headers, result = self.cloud.http("GET", api + "/build/definitions?includeAllProperties=true&%24top=1000&api-version=7.1",
                                            enrollment.ADO_AUDIENCE, tenant=self.config.get("ado_tenant_id") or self.target["tenant_id"])
        require(not headers.get("x-ms-continuationtoken"), "complete-ado-pipeline-inventory-required")
        matches = [item for item in result["value"] if item.get("repository", {}).get("id") == repository["id"]
                  and item.get("process", {}).get("yamlFilename", "").lstrip("/") == "aifactory/pipelines/factory-lifecycle.yml"]
        require(len(matches) <= 1, "ambiguous-factory-lifecycle-pipeline")
        return matches[0] if matches else None

    def ensure_pipeline(self):
        repository = self.discover()
        existing = self.pipeline(repository)
        if existing:
            return existing
        api = self.config["ado_organization"].rstrip("/") + "/" + quote(self.config["ado_project"], safe="") + "/_apis"
        self.cloud.read_only = False
        self.cloud.http("POST", api + "/pipelines?api-version=7.1", enrollment.ADO_AUDIENCE,
                       {"name": "AI Factory Lifecycle", "configuration": {"type": "yaml",
                        "path": "aifactory/pipelines/factory-lifecycle.yml",
                        "repository": {"id": repository["id"], "type": "azureReposGit"}}},
                       tenant=self.config.get("ado_tenant_id") or self.target["tenant_id"], allowed=(200, 201))
        created = self.pipeline(repository)
        require(created is not None, "factory-lifecycle-pipeline-not-verified")
        return created


def repository_url(provider, config):
    if provider == "gha":
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config["github_repository"]),
                "exact-github-repository-required")
        return "https://github.com/" + config["github_repository"]
    require(re.fullmatch(r"https://dev\.azure\.com/[A-Za-z0-9_-]+", config["ado_organization"]),
            "exact-ado-organization-required")
    return (config["ado_organization"] + "/" + quote(config["ado_project"], safe="") + "/_git/" +
            quote(config["ado_repository"], safe=""))


def prepare(*, consumer_root, scope, bootstrap_config, expected_revision, runtime=None):
    root = prerequisites.ordinary(consumer_root)
    target, register_hash = prerequisites._read_target(root, scope)
    document = enrollment.parse_json((root / "azurefactory" / "register.json").read_bytes())
    factory = next(item for item in document["factories"] if item["id"] == scope["factory_id"])
    providers = {item["orchestrator"] for item in factory["scale_sets"]}
    require(len(providers) == 1, "one-provider-per-factory-required")
    provider = providers.pop()
    config = {key: bootstrap_config[key] for key in (
        "github_repository", "github_visibility", "ado_organization", "ado_project",
        "ado_repository", "ado_tenant_id", "coordination_mode") if key in bootstrap_config}
    require(config.get("coordination_mode", "blob") in ("blob", "single-writer"), "unknown-coordination-mode")
    url = repository_url(provider, config)
    runtime = runtime or Repository(target, provider, config)
    remote = runtime.discover()
    private_project = None
    if config.get("coordination_mode") == "single-writer":
        require(provider != "gha" or config.get("github_visibility", "private") == "private",
                "single-writer-private-repository-required")
        require(not remote or (remote.get("private") is True if provider == "gha"
                               else remote.get("project", {}).get("visibility") == "private"),
                "single-writer-private-repository-required")
        if provider == "ado":
            private_project = runtime.private_project()
    pipeline = runtime.pipeline(remote) if provider == "ado" else None
    namespace, environment = None, None
    if provider == "gha":
        binding = document.get("bindings", {}).get(scope["factory_id"], {}).get(provider, {})
        old_target = next((item for item in binding.get("targets", [])
                           if item["scale_set_id"] == scope["scale_set_id"]), None)
        single_writer = config.get("coordination_mode") == "single-writer"
        execution = (old_target or {}).get("execution") or (binding if old_target or single_writer else None) or {}
        namespace_seed = ({"repository": url.lower(), "provider": provider, "coordination_mode": "single-writer"}
                          if single_writer else {
                              "factory": target["tenant_id"] + ":" + scope["factory_id"],
                              "subscription": target["subscription_id"], "scale": scope["scale_set_id"],
                              "repository": url.lower(), "provider": provider})
        namespace = execution.get("auth_namespace") or "aifactory-" + enrollment.digest(namespace_seed)[:20]
        require(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", namespace), "invalid-auth-namespace")
        environment = runtime.environment(namespace) if remote else None
    existing = (root / ".git").exists()
    head = runtime.git(root, "rev-parse", "--verify", "HEAD", missing=True) if existing else None
    branch = runtime.git(root, "symbolic-ref", "--short", "HEAD", missing=True) if existing else None
    origin = runtime.git(root, "remote", "get-url", "origin", missing=True) if existing else None
    require(not origin or origin.removesuffix(".git").casefold() == url.casefold(), "consumer-origin-conflicts-with-reviewed-repository")
    require(not branch or branch == "main", "consumer-main-branch-required")
    source_ref = release_version.branch_for(target["aifactory_version"])
    source_tip = runtime.git(root, "ls-remote", SHARED_URL, "refs/heads/" + source_ref)
    require(re.fullmatch(r"[a-f0-9]{40}\s+refs/heads/" + re.escape(source_ref), source_tip),
            "published-source-ref-required")
    sha = source_tip.split()[0]
    source_assets = runtime.source_assets(sha)
    remote_tip = runtime.git(root, "ls-remote", url, "refs/heads/main") if remote else ""
    require(not remote or not runtime.git(root, "ls-remote", url, LOCK_REF),
            "existing-initializer-lock-requires-reconciliation")
    remote_sha = remote_tip.split()[0] if remote_tip else None
    require(not remote_sha or remote_sha == head, "existing-remote-main-must-match-local-head")
    shared = prerequisites.ordinary(root / SHARED_PATH)
    modules_path = prerequisites.ordinary(root / ".gitmodules")
    modules_hash = hashlib.sha256(modules_path.read_bytes()).hexdigest() if modules_path.is_file() else None
    if head:
        require(not runtime.git(root, "diff", "--name-only", "HEAD", "--", ".gitmodules"),
                "dirty-gitmodules-needs-reconciliation")
    shared_sha = runtime.git(shared, "rev-parse", "HEAD", missing=True) if shared.is_dir() else None
    require(not shared.exists() or shared_sha == sha, "existing-shared-source-pin-conflict")
    plan = {"contract_version": 1, "stage": "repository-initialization", "plan_id": str(uuid4()),
            "expires_at": time.time() + 900, "consumer_root": str(root), "scope": scope,
            "target": target, "config": config, "provider": provider, "repository": url,
            "expected_revision": expected_revision, "register_hash": register_hash,
            "existing_git": existing, "head": head, "origin": origin, "remote_id": remote.get("id") if remote else None,
            "gitmodules_sha256": modules_hash,
            "pipeline": pipeline,
            "auth_namespace": namespace, "environment": environment,
            "remote_sha": remote_sha, "source": {"url": SHARED_URL, "ref": source_ref, "sha": sha,
                                                "verification": "published-remote-ref", "assets": source_assets},
            "application_helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "effects": ["Create or reuse exactly one reviewed provider repository.",
                        "Initialize missing Git metadata without replacing existing saved files or the user's index.",
                        "Pin the published accelerator submodule and its scoped provider workflow/private probe, not the saved draft.",
                        "For GitHub, create or reuse only environment " + (namespace or "(not applicable)") +
                        " through create-or-return; preserve existing protection and branch policies unchanged.",
                        "For Azure DevOps, create or reuse the exact repository-bound lifecycle YAML pipeline."],
            "can_execute": True, "blockers": []}
    if config.get("coordination_mode") == "single-writer":
        plan["private_project"] = private_project
        plan["warnings"] = [enrollment._single_writer_module().WARNING, enrollment._single_writer_module().HUB_WARNING,
                            "Single-writer coordination requires a private repository; repository visibility is never changed automatically."]
        plan["effects"][2] = "Pin the published accelerator, repository-state helpers and single-writer scoped workflow; no Blob coordination/private probe."
    plan["plan_hash"] = enrollment.digest(plan)
    return plan


def execute(plan, *, state_dir, runtime=None):
    require(enrollment.digest({k: v for k, v in plan.items() if k != "plan_hash"}) == plan["plan_hash"],
            "repository-plan-changed")
    require(time.time() < plan["expires_at"], "repository-review-expired")
    runtime = runtime or Repository(plan["target"], plan["provider"], plan["config"])
    fresh = prepare(consumer_root=plan["consumer_root"], scope=plan["scope"],
                    bootstrap_config=plan["config"], expected_revision=plan["expected_revision"], runtime=runtime)
    for key in ("register_hash", "existing_git", "head", "origin", "remote_id", "remote_sha", "source",
                "application_helper_sha256", "gitmodules_sha256", "pipeline", "auth_namespace", "environment"):
        require(fresh[key] == plan[key], "repository-discovery-changed:" + key)
    if plan["config"].get("coordination_mode") == "single-writer":
        require(fresh.get("private_project") == plan.get("private_project"), "repository-private-project-changed")
    root, folder = Path(plan["consumer_root"]), prerequisites.ordinary(state_dir)
    folder.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / (plan["plan_id"] + ".json")
    receipt = {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "status": "running",
               "repository": plan["repository"], "source": plan["source"], "reconciliation_required": True}
    with receipt_path.open("xb") as stream:
        stream.write(enrollment.canonical(receipt))
    try:
        if plan["remote_id"] is None:
            runtime.create()
        remote = runtime.discover()
        require(remote is not None, "repository-creation-not-verified")
        if plan["config"].get("coordination_mode") == "single-writer":
            require(remote.get("private") is True if plan["provider"] == "gha"
                    else remote.get("project", {}).get("visibility") == "private",
                    "single-writer-private-repository-required")
        if not plan["existing_git"]:
            runtime.git(root, "init", "--initial-branch=main")
        if not plan["origin"]:
            runtime.git(root, "remote", "add", "origin", plan["repository"])
        source = root / SHARED_PATH
        if not source.exists():
            runtime.git(root, "clone", "--no-checkout", "--", SHARED_URL, str(source))
            runtime.git(source, "checkout", "--detach", plan["source"]["sha"])
        require(runtime.git(source, "rev-parse", "HEAD") == plan["source"]["sha"], "source-pin-not-verified")
        projected = {
            (".github/workflows/factory-lifecycle.yml" if plan["provider"] == "gha" else "aifactory/pipelines/factory-lifecycle.yml"):
                "bootstrap/templates/factory-lifecycle-" + plan["provider"] + ".yml",
            ".azurefactory/hub_private_probe.py": "bootstrap/templates/hub_private_probe.py",
        }
        if plan["config"].get("coordination_mode") == "single-writer":
            projected.pop(".azurefactory/hub_private_probe.py")
            for destination in projected:
                projected[destination] = "bootstrap/templates/factory-lifecycle-single-writer-" + plan["provider"] + ".yml"
        projections = {}
        for destination, relative in projected.items():
            content = runtime.git(source, "cat-file", "blob", plan["source"]["sha"] + ":" + relative, raw=True)
            require(isinstance(content, bytes), "published-bootstrap-asset-bytes-required:" + relative)
            blob_hash = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            require(plan["source"]["assets"].get(relative) == blob_hash,
                    "published-bootstrap-asset-hash-mismatch:" + relative)
            data = content.replace(b"\r\n", b"\n")
            destination_path = prerequisites.ordinary(root / destination)
            require(not destination_path.exists() or destination_path.read_bytes().replace(b"\r\n", b"\n") == data,
                    "existing-provider-asset-conflicts:" + destination)
            if not destination_path.exists():
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                destination_path.write_bytes(data)
            projections[destination] = data
        # An isolated index excludes unrelated staged files from the generated commit.
        index = folder / (plan["plan_id"] + ".index")
        environment = {"GIT_INDEX_FILE": str(index), "GIT_AUTHOR_NAME": "AI Factory Bootstrap",
                       "GIT_AUTHOR_EMAIL": "aifactory-bootstrap@users.noreply.github.com",
                       "GIT_COMMITTER_NAME": "AI Factory Bootstrap",
                       "GIT_COMMITTER_EMAIL": "aifactory-bootstrap@users.noreply.github.com"}
        runtime.git(root, "read-tree", plan["head"] or "--empty", environment=environment)
        gitmodules = ('[submodule "' + SHARED_PATH + '"]\n\tpath = ' + SHARED_PATH + '\n\turl = ' + SHARED_URL + '\n').encode()
        module_path = prerequisites.ordinary(root / ".gitmodules")
        if module_path.exists():
            require(runtime.git(root, "config", "--file", str(module_path),
                                "--get", "submodule." + SHARED_PATH + ".path") == SHARED_PATH
                    and runtime.git(root, "config", "--file", str(module_path),
                                    "--get", "submodule." + SHARED_PATH + ".url").removesuffix(".git") == SHARED_URL,
                    "existing-gitmodules-conflict")
            gitmodules = module_path.read_bytes()
        else:
            module_path.write_bytes(gitmodules)
        blob = runtime.git(root, "hash-object", "-w", "--stdin", data=gitmodules)
        runtime.git(root, "update-index", "--add", "--cacheinfo", "100644," + blob + ",.gitmodules", environment=environment)
        runtime.git(root, "update-index", "--add", "--cacheinfo", "160000," + plan["source"]["sha"] + "," + SHARED_PATH,
                    environment=environment)
        projection_blobs = {}
        for destination, data in projections.items():
            projection_blobs[destination] = runtime.git(root, "hash-object", "-w", "--stdin", data=data)
            runtime.git(root, "update-index", "--add", "--cacheinfo",
                        "100644," + projection_blobs[destination] + "," + destination, environment=environment)
        tree = runtime.git(root, "write-tree", environment=environment)
        commit = runtime.git(root, "commit-tree", tree, *(("-p", plan["head"]) if plan["head"] else ()),
                             data=b"Initialize reviewed AI Factory source pin\n", environment=environment)
        receipt["commit"] = commit
        prerequisites._persist(receipt_path, receipt)
        lock_commit = runtime.git(root, "commit-tree", tree, "-p", commit,
                                  data=("Exclusive initializer " + plan["plan_id"] + "\n").encode(), environment=environment)
        receipt["provider_serialization"] = {"repository": plan["repository"], "ref": LOCK_REF,
                                             "sha": lock_commit, "owner": plan["plan_id"]}
        prerequisites._persist(receipt_path, receipt)
        runtime.git(root, "push", "--force-with-lease=" + LOCK_REF + ":", "origin", lock_commit + ":" + LOCK_REF)
        require(runtime.git(root, "ls-remote", plan["repository"], LOCK_REF).split()[0] == lock_commit,
                "provider-serialization-not-verified")
        runtime.git(root, "update-ref", "refs/heads/main", commit, plan["head"] or "0" * 40)
        runtime.git(root, "update-index", "--add", "--cacheinfo", "100644," + blob + ",.gitmodules")
        runtime.git(root, "update-index", "--add", "--cacheinfo", "160000," + plan["source"]["sha"] + "," + SHARED_PATH)
        for destination, content_hash in projection_blobs.items():
            runtime.git(root, "update-index", "--add", "--cacheinfo", "100644," + content_hash + "," + destination)
        runtime.git(root, "push", "--force-with-lease=refs/heads/main:" + (plan["remote_sha"] or ""),
                    "origin", commit + ":refs/heads/main")
        require(runtime.git(root, "ls-remote", plan["repository"], "refs/heads/main").split()[0] == commit,
                "repository-publication-not-verified")
        if plan["remote_id"] is None:
            runtime.set_initial_default_branch()
        if plan["provider"] == "ado":
            require(runtime.git(root, "ls-remote", plan["repository"], LOCK_REF).strip()
                    == receipt["provider_serialization"]["sha"] + "\t" + LOCK_REF, "provider-initializer-lock-not-held")
            receipt["pipeline_id"] = runtime.ensure_pipeline()["id"]
        else:
            require(runtime.git(root, "ls-remote", plan["repository"], LOCK_REF).strip()
                    == receipt["provider_serialization"]["sha"] + "\t" + LOCK_REF, "provider-initializer-lock-not-held")
            receipt["environment"] = runtime.ensure_environment(plan["auth_namespace"], plan["environment"])
        require(hashlib.sha256((root / "azurefactory" / "register.json").read_bytes()).hexdigest() == plan["register_hash"],
                "saved-draft-changed")
        receipt.update(status="succeeded", reconciliation_required=False,
                       outputs={"repository": {"url": plan["repository"], "provider": plan["provider"],
                                               "commit": commit, "source": plan["source"]},
                                "bindings": {"published_source": dict(plan["source"])},
                                "provider_serialization": receipt["provider_serialization"]})
        prerequisites._persist(receipt_path, receipt)
        index.unlink(missing_ok=True)
        return receipt
    except Exception as exc:
        receipt.update(status="uncertain", error=getattr(exc, "code", "repository-initialization-interrupted"))
        prerequisites._persist(receipt_path, receipt)
        return receipt
