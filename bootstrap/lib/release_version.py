"""AI Factory release selection. Consumer branches are deliberately unrelated."""

import argparse
import configparser
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

CONTRACT = "AIFACTORY_VERSION_CONTRACT=1"
DEFAULT_VERSION = "124"
SOURCE_URL = "https://github.com/jostrm/azure-enterprise-scale-ml"
STATE_PATH = Path("aifactory/config-wizard/aifactory-version.json")


def normalize(value):
    if not isinstance(value, str):
        raise ValueError("AI Factory version must be 124, a dotted major.minor version, or main.")
    if value == "main":
        return value
    if re.fullmatch(r"[1-9][0-9]{2}", value):
        major, minor = int(value[0]), int(value[1:])
    elif re.fullmatch(r"[1-9][0-9]{0,5}\.(?:0|[1-9][0-9]{0,5})", value):
        major, minor = map(int, value.split("."))
    else:
        raise ValueError("AI Factory version must be 124, a dotted major.minor version, or main.")
    return f"{major}{minor:02d}" if major < 10 and minor < 100 else f"{major}.{minor}"


def branch_for(value):
    value = normalize(value)
    if value == "main":
        return value
    dotted = value if "." in value else f"{int(value[0])}.{int(value[1:])}"
    return "release/v" + dotted


def version_for_branch(branch):
    if branch == "main":
        return "main"
    if not isinstance(branch, str) or not branch.startswith("release/v"):
        raise ValueError("Only main or release/v<major>.<minor> template branches are supported.")
    return normalize(branch[len("release/v"):])


def select(requested=None, *, saved=None, environ=None):
    env = os.environ if environ is None else environ
    explicit = [normalize(requested)] if requested is not None else []
    if env.get("AIFACTORY_VERSION"):
        explicit.append(normalize(env["AIFACTORY_VERSION"]))
    if env.get("AIF_SUBMODULE_BRANCH"):
        explicit.append(version_for_branch(env["AIF_SUBMODULE_BRANCH"]))
    if len(set(explicit)) > 1:
        raise ValueError("Conflicting explicit AI Factory version/branch selectors.")
    value = explicit[0] if explicit else normalize(saved or DEFAULT_VERSION)
    ref = env.get("AIF_SUBMODULE_REF", "")
    if ref and not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError("AIF_SUBMODULE_REF must be an exact lowercase 40-character commit.")
    return {"requested_version": value, "branch": branch_for(value), "resolved_ref": ref}


def saved_version(root):
    root = Path(root)
    record = root / STATE_PATH
    for path in (record, root / "aifactory/config-wizard/factory_state.json", root / "aifactory/variables.json", root / ".gitmodules"):
        if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
            raise ValueError("Version state cannot traverse links.")
        if path.is_file() and path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Version state exceeds the supported size.")
    if record.is_file():
        data = json.loads(record.read_text(encoding="utf-8-sig"))
        selected = select(data["requested_version"], environ={})
        if data.get("branch") != selected["branch"] or not re.fullmatch(r"[0-9a-f]{40}", data.get("resolved_ref", "")):
            raise ValueError("Saved AI Factory version record is inconsistent.")
        return selected["requested_version"]
    for file in (root / "aifactory/config-wizard/factory_state.json", root / "aifactory/variables.json"):
        if not file.is_file():
            continue
        data = json.loads(file.read_text(encoding="utf-8-sig"))
        sections = [data]
        sections.extend(data.get(key, {}) for key in ("state", "values", "factory", "variables"))
        for values in sections:
            if not isinstance(values, dict):
                continue
            if values.get("aifactory_version"):
                return normalize(str(values["aifactory_version"]))
            if values.get("version_branch") == "main":
                return "main"
            for major, minor in (("version_major", "version_minor"), ("aifactory_version_major", "aifactory_version_minor")):
                if major in values and minor in values:
                    return normalize(f"{values[major]}.{values[minor]}")
    modules = root / ".gitmodules"
    if modules.is_file():
        config = configparser.ConfigParser()
        config.read(modules, encoding="utf-8")
        for section in config.sections():
            if config.get(section, "path", fallback="") == "azure-enterprise-scale-ml":
                branch = config.get(section, "branch", fallback="")
                if branch:
                    return version_for_branch(branch)
    if (root / "aifactory").is_dir():
        raise ValueError("Existing factory version is unknown; save or supply its actual installed version before upgrading.")
    return None


def resolve(selected, read, *, repository=None):
    remote = read(["ls-remote", "--exit-code", SOURCE_URL, "refs/heads/" + selected["branch"]]).split()
    if len(remote) != 2 or remote[1] != "refs/heads/" + selected["branch"] or not re.fullmatch(r"[0-9a-f]{40}", remote[0]):
        raise ValueError("Selected AI Factory branch is not published; no fallback is allowed.")
    if selected["resolved_ref"] and selected["resolved_ref"] != remote[0]:
        if repository is None:
            raise ValueError("Explicit AI Factory ref conflicts with the selected published branch.")
        try:
            output = read(["-C", str(repository), "merge-base", "--is-ancestor", selected["resolved_ref"], remote[0]])
        except subprocess.SubprocessError:
            raise ValueError("Explicit AI Factory ref is not a verified published ancestor of the selected branch.") from None
        if output:
            raise ValueError("Explicit AI Factory ref ancestry could not be verified.")
    return {**selected, "resolved_ref": selected["resolved_ref"] or remote[0]}


def save(root, selected):
    expected = select(selected["requested_version"], environ={})
    if selected["branch"] != expected["branch"] or not re.fullmatch(r"[0-9a-f]{40}", selected["resolved_ref"]):
        raise ValueError("Cannot persist an unresolved AI Factory version.")
    path = Path(root) / STATE_PATH
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
        raise ValueError("Version state cannot traverse links.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, **selected}, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--aifactory-version")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--project-only", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    has_explicit_version = any((
        args.aifactory_version,
        os.environ.get("AIFACTORY_VERSION"),
        os.environ.get("AIF_SUBMODULE_BRANCH"),
    ))
    selected = select(
        args.aifactory_version,
        saved=None if has_explicit_version else saved_version(args.root),
    )
    if args.save:
        save(args.root, selected)
        return
    if not args.non_interactive and sys.stdin.isatty() and not any((
        args.aifactory_version, os.environ.get("AIFACTORY_VERSION"),
        os.environ.get("AIF_SUBMODULE_BRANCH"), os.environ.get("AIF_SUBMODULE_REF"),
    )):
        print(f"Default AI Factory version to create with will be {selected['requested_version']}, meaning branch {selected['branch']}. "
              "Hit ENTER if OK, or enter another version such as 125: ", end="", file=sys.stderr, flush=True)
        answer = input()
        selected = select(answer or selected["requested_version"], environ={})

    def read(argv):
        result = subprocess.run(["git", *argv], capture_output=True, text=True, check=True,
                                timeout=45, encoding="utf-8", errors="replace",
                                env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"})
        return result.stdout.strip()

    if args.project_only:
        installed = saved_version(args.root)
        if not installed or selected["requested_version"] != installed:
            raise ValueError("Selecting another version requires Patch or a prior upgrade; project-only preserves installed code.")
        ref = read(["-C", str(Path(args.root) / "azure-enterprise-scale-ml"), "rev-parse", "HEAD"])
        if selected["resolved_ref"] and selected["resolved_ref"] != ref:
            raise ValueError("Reviewed installed AI Factory commit changed.")
        selected["resolved_ref"] = ref
    else:
        source = Path(__file__).resolve().parents[2]
        installed_source = Path(args.root) / "azure-enterprise-scale-ml"
        if (installed_source / ".git").exists():
            source = installed_source
        selected = resolve(selected, read, repository=source if (source / ".git").exists() else None)
        if (source / ".git").exists():
            # ls-remote resolves the SHA but does not make its objects available for contract inspection.
            read(["-C", str(source), "fetch", "--no-tags", SOURCE_URL, selected["resolved_ref"]])
            for relative in ("bootstrap/lib/release_version.py", "bootstrap/lib/create-new-aifactory-scaleset.sh"):
                text = read(["-C", str(source), "show", selected["resolved_ref"] + ":" + relative])
                if CONTRACT not in text:
                    raise ValueError("Selected published release lacks the version contract; no fallback is allowed.")
        elif os.environ.get("AIFACTORY_VERSION_REVIEWED") != "1":
            raise ValueError("Fetch the selected release into the local accelerator before reviewing its contract.")
    for name, field in (("AIFACTORY_VERSION", "requested_version"), ("AIF_SUBMODULE_BRANCH", "branch"), ("AIF_SUBMODULE_REF", "resolved_ref")):
        print(f"export {name}={shlex.quote(selected[field])}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        sys.exit("AI Factory version selection failed: " + str(exc))
