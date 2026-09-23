"""Legacy entrypoints cannot silently reinterpret scoped creation as project001."""

import os
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[4]
BASH = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
if not BASH.is_file():
    BASH = shutil.which("bash")

CONTROL_LIBRARIES = (
    "aifactory_private_dns.py", "aifactory_scaleset_config.py",
    "aifactory_vpn_profile.py", "create-new-aifactory-scaleset.sh",
    "factory_enrollment.py", "factory_enrollment_entry.py", "factory_lifecycle.py",
    "layout_router.sh", "project_deployment.py", "project_environment.py",
    "registered_creation.py",
    "release_version.py", "release_version.sh",
    "runner-prerequisites.ps1", "runner-prerequisites.sh",
    "runner-registration.ps1", "runner-registration.sh",
    "runner_bootstrap.py", "runner-only-registration.sh",
)


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("provider", ["ADO", "GHA"])
@pytest.mark.parametrize("launcher", ["azurefactory.sh", "create-new-aifactory-scaleset.sh", "dispatcher"])
@pytest.mark.parametrize("action", ["plan", "ensure"])
@pytest.mark.parametrize("adapter_in_submodule", [False, True])
def test_enrollment_wrappers_preserve_provider_arguments_and_exit_status(
        tmp_path, provider, launcher, action, adapter_in_submodule):
    root = tmp_path / "registered consumer"
    library = root / "lib"
    library.mkdir(parents=True)
    shutil.copyfile(ROOT / "bootstrap/lib/layout_router.sh", library / "layout_router.sh")
    selected_name = f"{provider}-{launcher if launcher != 'dispatcher' else 'create-new-aifactory-scaleset.sh'}"
    shutil.copyfile(ROOT / "bootstrap" / selected_name, root / selected_name)
    if launcher == "dispatcher":
        selected_name = "ALL-create-new-aifactory-scaleset.sh"
        shutil.copyfile(ROOT / "bootstrap" / selected_name, root / selected_name)
    adapter_root = root / "azure-enterprise-scale-ml/bootstrap/lib" if adapter_in_submodule else library
    adapter_root.mkdir(parents=True, exist_ok=True)
    (adapter_root / "factory_enrollment_entry.py").write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(3)\n", encoding="utf-8",
    )
    (root / "azurefactory").mkdir()
    (root / "azurefactory/register.json").write_text('{"schema_version":2}', encoding="utf-8")
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    arguments = [
        action, "--consumer-root", str(root), "--factory-id", "fixture-factory",
        "--scale-set-id", "fixture-scaleset", "--environment", "stage",
        "--options", str(root / "approved options.json"),
    ]
    if action == "ensure":
        arguments += ["--expected-plan", "a" * 64, "--yes", "--acknowledge-exclusive-writer-governance"]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AIF_", "AIFACTORY_")) and key not in ("BASH_ENV", "ENV", "SHELLOPTS")}
    env["AIFACTORY_PYTHON"] = sys.executable
    prefix = ["--orchestrator", provider.lower()] if launcher == "dispatcher" else []
    result = subprocess.run(
        [str(BASH), "--noprofile", "--norc", str(root / selected_name), *prefix, "enroll", *arguments],
        cwd=root, env=env, input="", capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 3, result.stderr
    assert json.loads(result.stdout) == [provider.lower(), *arguments]
    assert before == {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("name,value", [
    ("AIF_CREATE_PROJECTS", "none"), ("AIF_CREATE_PROJECTS", "all"), ("AIF_PROJECT_MODE", "none"),
])
def test_scoped_creation_settings_fail_before_legacy_defaults_or_auth(name, value):
    env = {key: content for key, content in os.environ.items()
           if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "HOME", "USERPROFILE",
                              "TEMP", "TMP", "LOCALAPPDATA", "PROGRAMFILES"}}
    env[name] = value
    script = r'''
source bootstrap/lib/create-new-aifactory-scaleset.sh
aif_simple_stage() { printf 'FORBIDDEN_LEGACY_STAGE\n'; return 91; }
aif_collect_answers() { printf 'FORBIDDEN_PROJECT_DEFAULT\n'; return 92; }
aif_scaleset_main gha "$PWD/bootstrap/GHA-create-new-aifactory-scaleset.sh" --non-interactive --yes
'''
    result = subprocess.run([str(BASH), "--noprofile", "--norc", "-c", script],
                            cwd=ROOT, env=env, input="", capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode != 0
    assert "AIFactory-lifecycle.sh" in result.stderr
    assert "no implicit project001 fallback" in result.stderr
    assert "FORBIDDEN_" not in result.stdout


@pytest.fixture
def register_workspace():
    path = ROOT / (".register-launcher-test-" + str(uuid4()))
    (path / "azurefactory").mkdir(parents=True)
    (path / "azurefactory" / "register.json").write_text('{"schema": 2}', encoding="utf-8")
    try:
        yield path
    finally:
        shutil.rmtree(path)


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("launcher", [
    "ADO-create-new-aifactory-scaleset.sh", "GHA-create-new-aifactory-scaleset.sh",
    "ADO-update-aifactory-and-run-project.sh", "GH-update-aifactory-and-run-project.sh",
    "GHA-update-aifactory-and-run-project.sh",
])
@pytest.mark.parametrize("nested", [False, True])
def test_register_blocks_legacy_entrypoints_without_writes(register_workspace, launcher, nested):
    root = register_workspace
    destination = root / "azurefactory" / "factories" / "ai-marvel" if nested else root
    destination.mkdir(parents=True, exist_ok=True)
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    env = {key: value for key, value in os.environ.items() if not key.startswith(("AIF_", "AIFACTORY_", "ADO_"))}
    env.update(AIFACTORY_REPO_ROOT=str(destination), AIFACTORY_LAUNCHER_STABLE="1")
    args = [str(BASH), str(ROOT / "bootstrap" / launcher)]
    if "-create-" in launcher:
        args += ["--repo-root", str(destination), "--non-interactive", "--dry-run"]
    result = subprocess.run(args, cwd=root, env=env, input="", capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "azurefactory/register.json" in result.stderr
    assert "AIFactory-lifecycle.sh" in result.stderr
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert not (destination / "aifactory").exists()


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("launcher,route", [
    ("ADO-create-new-aifactory-scaleset.sh", "ado"),
    ("GHA-create-new-aifactory-scaleset.sh", "gha"),
    ("ADO-update-aifactory-and-run-project.sh", "ado"),
    ("GH-update-aifactory-and-run-project.sh", "gha"),
    ("GHA-update-aifactory-and-run-project.sh", "gha"),
])
@pytest.mark.parametrize("nested", [False, True])
def test_registered_roots_delegate_legacy_named_entrypoints_to_scoped_inspect(
        register_workspace, launcher, route, nested):
    fixtures = runpy.run_path(str(Path(__file__).with_name("test_factory_lifecycle.py")))
    document = fixtures["manifest"]("deploy-project")
    document["route"]["kind"] = route
    document["route"]["repository"] = (
        "https://github.com/org/consumer" if route == "gha"
        else "https://dev.azure.com/org/project/_git/consumer"
    )
    document["target"]["factory_type"] = "ai"
    root = register_workspace
    destination = root / "azurefactory/factories/ai-marvel" if nested else root
    destination.mkdir(parents=True, exist_ok=True)
    before = {str(path.relative_to(root)): path.read_bytes()
              for path in root.rglob("*") if path.is_file()}
    env = dict(os.environ, AIFACTORY_REPO_ROOT=str(destination),
               AIFACTORY_PYTHON=sys.executable)
    result = subprocess.run(
        [str(BASH), str(ROOT / "bootstrap" / launcher), "inspect", "--stdin-manifest"],
        cwd=root, env=env, input=json.dumps(fixtures["seal"](document)),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["manifest_valid"] is True
    assert before == {str(path.relative_to(root)): path.read_bytes()
                      for path in root.rglob("*") if path.is_file()}


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("provider,action", [
    ("ADO-azurefactory.sh", "legacy-create"),
    ("ADO-azurefactory.sh", "legacy-update"),
    ("GHA-azurefactory.sh", "legacy-create"),
    ("GHA-azurefactory.sh", "legacy-update"),
])
def test_scoped_provider_launchers_expose_explicit_legacy_compatibility(
        provider, action, tmp_path):
    legacy_root = tmp_path / "legacy-layout"
    legacy_root.mkdir()
    result = subprocess.run(
        [str(BASH), str(ROOT / "bootstrap" / provider), action, "--help"],
        cwd=legacy_root,
        env=dict(os.environ, AIFACTORY_REPO_ROOT=str(legacy_root)),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout + result.stderr


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("launcher", [
    "01-aif-copy-aifactory-templates.sh", "02a-GH-bootstrap-files.sh", "02b-ADO-YAML-bootstrap-files.sh",
    "03a-GH-bootstrap-files-no-env-overwrite.sh", "03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh",
])
def test_manual_template_launchers_block_register_before_copy(register_workspace, launcher):
    root = register_workspace
    script_root = root / "azure-enterprise-scale-ml" if launcher == "00-start.sh" else root
    library = script_root / ("bootstrap/ui" if launcher == "00-start.sh" else "ui")
    library.mkdir(parents=True)
    shutil.copyfile(ROOT / "bootstrap/ui/terminal.sh", library / "terminal.sh")
    shutil.copyfile(ROOT / (launcher if launcher == "00-start.sh" else "bootstrap/" + launcher), script_root / launcher)
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = subprocess.run([str(BASH), str(script_root / launcher)], cwd=root, input="",
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "azurefactory/register.json" in result.stderr
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
def test_start_installs_dual_layout_bundle_at_registered_root(register_workspace):
    root = register_workspace
    source = root / "azure-enterprise-scale-ml"
    (source / "bootstrap/ui").mkdir(parents=True)
    (source / "bootstrap/lib").mkdir(parents=True)
    shutil.copy2(ROOT / "00-start.sh", source / "00-start.sh")
    shutil.copy2(ROOT / "bootstrap/ui/terminal.sh", source / "bootstrap/ui/terminal.sh")
    for name in CONTROL_LIBRARIES:
        shutil.copy2(ROOT / "bootstrap/lib" / name, source / "bootstrap/lib" / name)
    scripts = (
        "ADO-azurefactory.sh", "ADO-create-new-aifactory-scaleset.sh",
        "ADO-update-aifactory-and-run-project.sh", "AIFactory-lifecycle.sh",
        "ALL-create-new-aifactory-scaleset.sh", "GH-update-aifactory-and-run-project.sh",
        "GHA-azurefactory.sh", "GHA-create-new-aifactory-scaleset.sh",
        "GHA-update-aifactory-and-run-project.sh",
    )
    for name in scripts:
        shutil.copy2(ROOT / "bootstrap" / name, source / "bootstrap" / name)
    register = root / "azurefactory/register.json"
    before = register.read_bytes()
    result = subprocess.run(
        [str(BASH), str(source / "00-start.sh")], cwd=root,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert register.read_bytes() == before
    assert all((root / name).is_file() for name in scripts)
    assert {path.name for path in (root / "lib").iterdir()} == set(CONTROL_LIBRARIES)
    for name in CONTROL_LIBRARIES:
        assert (root / "lib" / name).read_bytes() == (ROOT / "bootstrap/lib" / name).read_bytes()
    assert (root / "ui/terminal.sh").is_file()
    assert not (root / "aifactory").exists()


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("route", ["ado", "gha"])
def test_all_dispatcher_delegates_registered_inspect(register_workspace, route):
    fixtures = runpy.run_path(str(Path(__file__).with_name("test_factory_lifecycle.py")))
    document = fixtures["manifest"]("deploy-project")
    document["route"]["kind"] = route
    document["route"]["repository"] = (
        "https://github.com/org/consumer" if route == "gha"
        else "https://dev.azure.com/org/project/_git/consumer"
    )
    document["target"]["factory_type"] = "ai"
    result = subprocess.run(
        [str(BASH), str(ROOT / "bootstrap/ALL-create-new-aifactory-scaleset.sh"),
         "--orchestrator", route, "--repo-root", str(register_workspace),
         "inspect", "--stdin-manifest"],
        cwd=register_workspace,
        env=dict(os.environ, AIFACTORY_PYTHON=sys.executable),
        input=json.dumps(fixtures["seal"](document)),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["manifest_valid"] is True


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
def test_launcher_bundle_round_trip_preserves_all_control_entrypoints(tmp_path):
    snapshot, destination = tmp_path / "snapshot", tmp_path / "destination"
    destination.mkdir()
    (destination / ".gitignore").write_text("/*\ncredentials.json", encoding="utf-8")
    (destination / "credentials.json").write_text("must-stay-ignored", encoding="utf-8")
    script = (
        f'source "{(ROOT / "bootstrap/lib/layout_router.sh").as_posix()}"\n'
        f'aif_snapshot_launcher_bundle "{(ROOT / "bootstrap").as_posix()}" "{snapshot.as_posix()}"\n'
        f'aif_restore_launcher_bundle "{snapshot.as_posix()}" "{destination.as_posix()}"\n'
    )
    result = subprocess.run(
        [str(BASH), "--noprofile", "--norc", "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    for name in (
        "ADO-azurefactory.sh", "ADO-create-new-aifactory-scaleset.sh",
        "ADO-update-aifactory-and-run-project.sh", "AIFactory-lifecycle.sh",
        "ALL-create-new-aifactory-scaleset.sh", "GH-update-aifactory-and-run-project.sh",
        "GHA-azurefactory.sh", "GHA-create-new-aifactory-scaleset.sh",
        "GHA-update-aifactory-and-run-project.sh",
    ):
        assert (destination / name).read_bytes() == (ROOT / "bootstrap" / name).read_bytes()
    assert {path.name for path in (snapshot / "lib").iterdir()} == set(CONTROL_LIBRARIES)
    assert {path.name for path in (destination / "lib").iterdir()} == set(CONTROL_LIBRARIES)
    for name in CONTROL_LIBRARIES:
        assert (destination / "lib" / name).read_bytes() == (
            ROOT / "bootstrap/lib" / name).read_bytes()
    assert (destination / "ui/terminal.sh").read_bytes() == (
        ROOT / "bootstrap/ui/terminal.sh").read_bytes()
    ignore = (destination / ".gitignore").read_text(encoding="utf-8")
    for name in CONTROL_LIBRARIES:
        assert "!/lib/" + name in ignore.splitlines()
    assert "!/ui/terminal.sh" in ignore
    assert ignore.startswith("/*\ncredentials.json\n")
    (destination / "lib/local-package.bin").write_bytes(b"ignored")
    subprocess.run(["git", "-C", str(destination), "init", "--quiet"], check=True)
    assert subprocess.run(
        ["git", "-C", str(destination), "check-ignore", "--quiet",
         "lib/layout_router.sh"]).returncode == 1
    assert subprocess.run(
        ["git", "-C", str(destination), "check-ignore", "--quiet",
         "lib/local-package.bin"]).returncode == 0
    assert subprocess.run(
        ["git", "-C", str(destination), "check-ignore", "--quiet",
         "ADO-azurefactory.sh"]).returncode == 1
    assert subprocess.run(
        ["git", "-C", str(destination), "check-ignore", "--quiet",
         "credentials.json"]).returncode == 0
    template_ignore = (ROOT / "bootstrap/.gitignore.template").read_text(encoding="utf-8")
    for name in CONTROL_LIBRARIES:
        assert "!/lib/" + name in template_ignore.splitlines()
    assert "\n!/lib/\n/lib/*\n" in template_ignore
    assert "\n!lib/\n" not in template_ignore


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("missing", CONTROL_LIBRARIES)
def test_incomplete_launcher_bundle_fails_before_snapshot(tmp_path, missing):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "bootstrap", source, ignore=shutil.ignore_patterns("__pycache__"))
    helper = source / "lib" / missing
    helper.rename(helper.with_name(helper.name + ".unavailable"))
    snapshot = tmp_path / "snapshot"
    result = subprocess.run(
        [str(BASH), "--noprofile", "--norc", "-c",
         'source "$1/lib/layout_router.sh"; aif_snapshot_launcher_bundle "$2" "$3"',
         "bundle-test", str(ROOT / "bootstrap"), str(source), str(snapshot)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "Complete dual-layout launcher bundle" in result.stderr
    assert not snapshot.exists()


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
def test_launcher_bundle_restore_reports_copy_failure(tmp_path):
    snapshot = tmp_path / "snapshot"
    script = (
        f'source "{(ROOT / "bootstrap/lib/layout_router.sh").as_posix()}"\n'
        f'aif_snapshot_launcher_bundle "{(ROOT / "bootstrap").as_posix()}" "{snapshot.as_posix()}"\n'
        'cp() { return 9; }\n'
        f'aif_restore_launcher_bundle "{snapshot.as_posix()}" "{(tmp_path / "destination").as_posix()}"\n'
    )
    result = subprocess.run(
        [str(BASH), "--noprofile", "--norc", "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert snapshot.is_dir()


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("launcher", [
    "ADO-update-aifactory-and-run-project.sh",
    "GH-update-aifactory-and-run-project.sh",
    "GHA-update-aifactory-and-run-project.sh",
])
def test_update_help_does_not_install_or_modify_bundle(tmp_path, launcher):
    root = tmp_path / "legacy"
    root.mkdir()
    marker = root / "existing.txt"
    marker.write_text("unchanged", encoding="utf-8")
    before = {str(path.relative_to(root)): path.read_bytes()
              for path in root.rglob("*") if path.is_file()}
    result = subprocess.run(
        [str(BASH), str(ROOT / "bootstrap" / launcher), "--help"],
        cwd=root, env=dict(os.environ, AIFACTORY_REPO_ROOT=str(root)),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert before == {str(path.relative_to(root)): path.read_bytes()
                      for path in root.rglob("*") if path.is_file()}


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
def test_legacy_workspace_guard_remains_read_only_and_allows_legacy(register_workspace):
    root = register_workspace
    (root / "azurefactory/register.json").unlink()
    (root / "aifactory").mkdir()
    (root / "aifactory/variables.json").write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [str(BASH), "-c", 'source "$1"; aif_require_legacy_workspace "$2"',
         "guard-test", str(ROOT / "bootstrap/ui/terminal.sh"), str(root)],
        cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert (root / "aifactory/variables.json").read_text(encoding="utf-8") == "{}"


@pytest.mark.skipif(not BASH, reason="Git Bash is unavailable")
@pytest.mark.parametrize("route", ["ado", "gha"])
@pytest.mark.parametrize("matches", [False, True])
def test_register_route_launchers_inspect_only_exact_manifest_without_writes(register_workspace, route, matches):
    fixtures = runpy.run_path(str(Path(__file__).with_name("test_factory_lifecycle.py")))
    document = fixtures["manifest"]("deploy-project")
    selected_route = route if matches else ("ado" if route == "gha" else "gha")
    document["route"]["kind"] = selected_route
    document["route"]["repository"] = ("https://github.com/org/consumer" if selected_route == "gha"
                                      else "https://dev.azure.com/org/project/_git/consumer")
    document["target"]["factory_type"] = "ai"
    env = dict(os.environ, AIFACTORY_PYTHON=sys.executable)
    root = register_workspace
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = subprocess.run(
        [str(BASH), str(ROOT / "bootstrap" / (route.upper() + "-azurefactory.sh")), "inspect",
         "--stdin-manifest", "--expected-orchestrator", selected_route],
        env=env, cwd=root, input=json.dumps(fixtures["seal"](document)), capture_output=True, text=True, timeout=30)
    output = json.loads(result.stdout)
    if matches:
        assert result.returncode == 0, result.stderr
        assert output["manifest_valid"]
    else:
        assert result.returncode == 2
        assert output["error_code"] == "orchestrator-mismatch"
    assert "synthetic-not-a-credential" not in result.stdout
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
