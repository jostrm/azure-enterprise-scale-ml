"""Read-only release selection for immutable deployment confirmations."""

import configparser
import json
import re
import subprocess
from pathlib import Path

from src.ticket_connectors import TicketError

DEFAULT_VERSION = "124"
SOURCE_URL = "https://github.com/jostrm/azure-enterprise-scale-ml"
CONTRACT = "AIFACTORY_VERSION_CONTRACT=1"
STATE_PATH = Path("aifactory/config-wizard/aifactory-version.json")


def normalize(value):
    if not isinstance(value, str):
        raise TicketError("AI Factory version must be 124, a dotted major.minor version, or main.")
    if value == "main":
        return value
    if re.fullmatch(r"[1-9][0-9]{2}", value):
        major, minor = int(value[0]), int(value[1:])
    elif re.fullmatch(r"[1-9][0-9]{0,5}\.(?:0|[1-9][0-9]{0,5})", value):
        major, minor = map(int, value.split("."))
    else:
        raise TicketError("AI Factory version must be 124, a dotted major.minor version, or main.")
    return f"{major}{minor:02d}" if major < 10 and minor < 100 else f"{major}.{minor}"


def branch_for(value):
    value = normalize(value)
    if value == "main":
        return value
    return "release/v" + (value if "." in value else f"{int(value[0])}.{int(value[1:])}")


def version_for_branch(branch):
    if branch == "main":
        return "main"
    if not isinstance(branch, str) or not branch.startswith("release/v"):
        raise TicketError("Only main or release/v<major>.<minor> template branches are supported.", 409)
    return normalize(branch[len("release/v"):])


def select(requested=None, *, saved=None, environ=None):
    # API requests never inherit process-wide selectors from another job.
    env = environ or {}
    explicit = [normalize(requested)] if requested is not None else []
    if env.get("AIFACTORY_VERSION"):
        explicit.append(normalize(env["AIFACTORY_VERSION"]))
    if env.get("AIF_SUBMODULE_BRANCH"):
        explicit.append(version_for_branch(env["AIF_SUBMODULE_BRANCH"]))
    if len(set(explicit)) > 1:
        raise TicketError("Conflicting explicit AI Factory version/branch selectors.")
    value = explicit[0] if explicit else normalize(saved or DEFAULT_VERSION)
    ref = env.get("AIF_SUBMODULE_REF", "")
    if ref and not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise TicketError("AIF_SUBMODULE_REF must be an exact lowercase 40-character commit.")
    return {"requested_version": value, "branch": branch_for(value), "resolved_ref": ref}


def saved_version(root):
    root = Path(root)
    try:
        record = root / STATE_PATH
        paths = [record, root / "aifactory/config-wizard/factory_state.json",
                 root / "aifactory/variables.json", root / ".gitmodules"]
        for path in paths:
            if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
                raise TicketError("Version state cannot traverse links.", 409)
            if path.is_file() and path.stat().st_size > 4 * 1024 * 1024:
                raise TicketError("Version state exceeds supported size.", 409)
        if record.is_file():
            data = json.loads(record.read_text(encoding="utf-8-sig"))
            selected = select(data["requested_version"])
            if data.get("branch") != selected["branch"] or not re.fullmatch(r"[0-9a-f]{40}", data.get("resolved_ref", "")):
                raise TicketError("Saved AI Factory version record is inconsistent.", 409)
            return selected["requested_version"]
        for path in paths[1:3]:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            for values in [data, *(data.get(key, {}) for key in ("state", "values", "factory", "variables"))]:
                if not isinstance(values, dict):
                    continue
                if values.get("aifactory_version"):
                    return normalize(str(values["aifactory_version"]))
                if values.get("version_branch") == "main":
                    return "main"
                for major, minor in (("version_major", "version_minor"), ("aifactory_version_major", "aifactory_version_minor")):
                    if major in values and minor in values:
                        return normalize(f"{values[major]}.{values[minor]}")
        if paths[3].is_file():
            config = configparser.ConfigParser()
            config.read(paths[3], encoding="utf-8")
            for section in config.sections():
                if config.get(section, "path", fallback="") == "azure-enterprise-scale-ml":
                    branch = config.get(section, "branch", fallback="")
                    if branch:
                        return version_for_branch(branch)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, configparser.Error):
        raise TicketError("Saved AI Factory version is malformed or unreadable.", 409) from None
    if (root / "aifactory").is_dir():
        raise TicketError("Existing factory version is unknown. Save its actual installed version before upgrading.", 409)
    return None


def resolve(selected, cli):
    remote = cli.read("git", ["ls-remote", "--exit-code", SOURCE_URL, "refs/heads/" + selected["branch"]], raw=True).split()
    if len(remote) != 2 or remote[1] != "refs/heads/" + selected["branch"] or not re.fullmatch(r"[0-9a-f]{40}", remote[0]):
        raise TicketError("Selected AI Factory branch is not published; no fallback is allowed.", 409)
    if selected["resolved_ref"] and selected["resolved_ref"] != remote[0]:
        raise TicketError("Explicit AI Factory ref conflicts with the selected published branch.", 409)
    return {**selected, "resolved_ref": remote[0]}


def project_selection(root, requested, patch, cli, route=None):
    installed = saved_version(root)
    selected = select(requested, saved=installed)
    shared = Path(root) / "azure-enterprise-scale-ml"
    if not patch:
        if selected["requested_version"] != installed:
            raise TicketError("Selecting another version requires Patch or a prior upgrade; project-only preserves installed code.", 409)
        ref = cli.read("git", ["-C", str(shared), "rev-parse", "HEAD"], raw=True).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", ref):
            raise TicketError("Installed AI Factory commit cannot be verified.", 409)
        return {**selected, "resolved_ref": ref}
    selected = resolve(selected, cli)
    for relative in ("bootstrap/lib/project_deployment.py", "bootstrap/lib/release_version.py"):
        text = cli.read("git", ["-C", str(shared), "show", selected["resolved_ref"] + ":" + relative], raw=True)
        if CONTRACT not in text:
            raise TicketError("Selected published release lacks the reviewed version contract. Publish/fetch compatible source; no fallback.", 409)
    if route:
        if route == "gha":
            base = "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/"
            files = ("infra-project.yml", "infra-project-phase.yml")
        else:
            base = "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/"
            files = ("infra-project-genai.yaml", "jobs/job-0-reviewed-project-config.yaml")
        for file in files:
            text = cli.read("git", ["-C", str(shared), "show", selected["resolved_ref"] + ":" + base + file], raw=True)
            if "AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1" not in text:
                raise TicketError("Selected published pipeline lacks the reviewed project contract; no fallback.", 409)
    return selected


def environment(selected):
    return {"AIFACTORY_VERSION": selected["requested_version"], "AIF_SUBMODULE_BRANCH": selected["branch"],
            "AIF_SUBMODULE_REF": selected["resolved_ref"], "AIFACTORY_VERSION_REVIEWED": "1"}


def _source_path(value):
    path = Path(value)
    if not path.is_absolute() or any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                                     for p in (path, *path.parents)):
        raise TicketError("Published source paths must be absolute and cannot traverse links.", 409)
    return path.resolve()


def published_source(requested, cli, source_root, *, saved=None, required_paths=None):
    """Read-only preview; required_paths maps trusted relative files to contract markers."""
    root = _source_path(source_root)
    if not root.is_dir() or not (root / ".git").exists():
        raise TicketError("The local published-source repository is unavailable.", 409)
    selected = resolve(select(requested, saved=saved), cli)
    ref = selected["resolved_ref"]
    cli.read("git", ["-C", str(root), "cat-file", "-e", ref + "^{commit}"], raw=True)
    requirements = {"bootstrap/lib/release_version.py": CONTRACT, **(required_paths or {})}
    for relative, marker in requirements.items():
        path = Path(relative)
        if path.is_absolute() or path.drive or ".." in path.parts or ":" in relative or "\\" in relative:
            raise TicketError("Unsupported published-source contract path.", 409)
        content = cli.read("git", ["-C", str(root), "show", ref + ":" + relative], raw=True)
        if not marker or marker not in content:
            raise TicketError("Selected published release lacks a required lifecycle contract; no fallback.", 409)
    return {**selected, "source_root": str(root)}


def materialize_source(source_root, resolved_ref, destination, *, git="git", runner=None):
    """After confirmation only: create an independent pinned Git checkout for one job."""
    from src.simple_mode import launch_environment

    root, target = _source_path(source_root), _source_path(destination)
    if not root.is_dir() or not (root / ".git").exists() or target.exists() or target.is_relative_to(root) or root.is_relative_to(target):
        raise TicketError("Use a new isolated source directory outside the selected repository.", 409)
    if not isinstance(resolved_ref, str) or not re.fullmatch(r"[0-9a-f]{40}", resolved_ref):
        raise TicketError("An exact reviewed source commit is required.", 409)
    run = runner or subprocess.run
    env = launch_environment({}, {"git": git})
    hooks = str(target / ".git" / "aifactory-disabled-hooks")

    def command(arguments):
        try:
            result = run([git, "-c", "core.hooksPath=" + hooks, "-c", "core.fsmonitor=false", *arguments], shell=False,
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=120, env=env)
        except (OSError, subprocess.SubprocessError):
            raise TicketError("Could not materialize the reviewed source; inspect the isolated artifact before retrying.", 409) from None
        if result.returncode:
            raise TicketError("Could not materialize the reviewed source; no deployment was started.", 409)
        return result.stdout.strip()

    target.parent.mkdir(parents=True, exist_ok=True)
    command(["clone", "--local", "--no-hardlinks", "--dissociate", "--no-checkout", "--", str(root), str(target)])
    command(["-C", str(target), "remote", "set-url", "origin", SOURCE_URL])
    command(["-C", str(target), "checkout", "--detach", resolved_ref])
    if command(["-C", str(target), "rev-parse", "HEAD"]) != resolved_ref:
        raise TicketError("Isolated source does not match the reviewed commit.", 409)
    if command(["-C", str(target), "status", "--porcelain", "--untracked-files=all"]):
        raise TicketError("Isolated reviewed source is not clean.", 409)
    return str(target)
