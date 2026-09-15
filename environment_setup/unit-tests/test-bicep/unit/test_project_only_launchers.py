"""Offline contract tests for project-only update launchers."""

from pathlib import Path
import os
import json
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[4]
LAUNCHERS = [
    ROOT / "bootstrap" / "ADO-update-aifactory-and-run-project.sh",
    ROOT / "bootstrap" / "GH-update-aifactory-and-run-project.sh",
]


def copy_launcher_bundle(destination):
    for folder, patterns in (("", ("*.sh",)), ("lib", ("*.py", "*.sh")), ("ui", ("terminal.sh",))):
        target = destination / folder
        target.mkdir(parents=True, exist_ok=True)
        for pattern in patterns:
            for source in (ROOT / "bootstrap" / folder).glob(pattern):
                shutil.copyfile(source, target / source.name)


def test_project_only_flag_skips_update_and_publish_operations() -> None:
    for launcher in LAUNCHERS:
        source = launcher.read_text(encoding="utf-8")
        assert "--project-only" in source
        assert "AIFACTORY_PROJECT_ONLY" in source
        project_only_block = source.split(
            'if [[ "$project_only" == "true" ]]; then\n'
            '  aif_section "03 / Project-only mode"',
            1,
        )[1].split("\nelse\n", 1)[0]
        assert 'if [[ "$project_only" == "false" ]]; then' in source
        pinned_update = (
            "git submodule update --init --recursive",
            'git -C "$SUBMODULE_PATH" fetch origin "$AIF_SUBMODULE_REF"',
            'git -C "$SUBMODULE_PATH" checkout --detach "$AIF_SUBMODULE_REF"',
            'aif_version_save "$REPO_ROOT"',
        )
        assert "\n  ".join(pinned_update) in source
        assert "git submodule update --init --recursive --remote" not in source
        assert "git pull --ff-only origin" in source
        assert 'aif_info "Skipping submodule pull, template refresh' in source
        for operation in (
            *pinned_update,
            "git pull --ff-only origin",
            "01-aif-copy-aifactory-templates.sh",
            "03-GH-bootstrap-files-no-env-overwrite.sh",
            "03-ADO-YAML-bootstrap-files-no-var-overwrite.sh",
            "10-GH-create-or-update-github-variables.sh",
            "git add -A",
            "git push origin",
        ):
            assert operation not in project_only_block


@pytest.fixture
def bash_executable():
    candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
    bash = str(candidate) if os.name == "nt" and candidate.is_file() else shutil.which("bash")
    if not bash:
        pytest.skip("Bash is required for offline launcher tests.")
    return bash


def parse_launcher(launcher, args, environment, bash_executable):
    source = launcher.read_text(encoding="utf-8")
    parser = source.split('launcher_arguments=("$@")', 1)[1].split('\ncd "$REPO_ROOT"', 1)[0]
    script = (
        'set -euo pipefail\n'
        'aif_error() { printf "%s\\n" "$*" >&2; }\n'
        'git() { echo "Unexpected git mutation" >&2; exit 99; }\n'
        'az() { echo "Unexpected Azure command" >&2; exit 99; }\n'
        'gh() { echo "Unexpected GitHub command" >&2; exit 99; }\n'
        'launcher_arguments=("$@")' + parser +
        '\nprintf "TARGET=%s PROJECT_ONLY=%s\\n" "$ENVIRONMENT" "$project_only"\n'
    )
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AIFACTORY_", "AIF_")) and key not in ("BASH_ENV", "ENV", "SHELLOPTS")}
    env.update(environment)
    return subprocess.run([bash_executable, "--noprofile", "--norc", "-c", script, "launcher", *args],
                          capture_output=True, text=True, env=env, timeout=30)


@pytest.mark.parametrize("launcher", LAUNCHERS, ids=lambda path: path.name.split("-")[0])
@pytest.mark.parametrize("args,environment,target", [
    ([], {}, "dev"),
    (["--aifactory-env", "dev"], {}, "dev"),
    (["--aifactory-env", "stage"], {}, "stage"),
    (["--aifactory-env=prod"], {}, "prod"),
    ([], {"AIFACTORY_TARGET_ENVIRONMENT": "stage"}, "stage"),
    (["--aifactory-env", "prod"], {"AIFACTORY_TARGET_ENVIRONMENT": "prod"}, "prod"),
])
def test_environment_parser_preserves_default_and_reviewed_inputs(launcher, args, environment, target, bash_executable):
    result = parse_launcher(launcher, [*args, "--project-only"], environment, bash_executable)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"TARGET={target} PROJECT_ONLY=true"


@pytest.mark.parametrize("launcher", LAUNCHERS, ids=lambda path: path.name.split("-")[0])
@pytest.mark.parametrize("args,environment", [
    (["--aifactory-env"], {}),
    (["--aifactory-env="], {}),
    (["--aifactory-env", "qa"], {}),
    (["--aifactory-env", "--project-only"], {}),
    (["--aifactory-env", "dev", "--aifactory-env=dev"], {}),
    (["--aifactory-env=prod", "--aifactory-env", "stage"], {}),
    (["--aifactory-env=stage"], {"AIFACTORY_TARGET_ENVIRONMENT": "prod"}),
    ([], {"AIFACTORY_TARGET_ENVIRONMENT": "test"}),
    ([], {"AIFACTORY_TARGET_ENVIRONMENT": ""}),
])
def test_bad_environment_fails_before_commands(launcher, args, environment, bash_executable):
    result = parse_launcher(launcher, args, environment, bash_executable)
    assert result.returncode == 1
    assert "TARGET=" not in result.stdout
    assert "Unexpected" not in result.stderr
    assert "env" in result.stderr.lower()


def test_alias_forwards_environment_and_project_only_unchanged(tmp_path, bash_executable):
    alias = ROOT / "bootstrap/GHA-update-aifactory-and-run-project.sh"
    copied = tmp_path / alias.name
    copied.write_bytes(alias.read_bytes())
    (tmp_path / "GH-update-aifactory-and-run-project.sh").write_text(
        'printf "<%s>\\n" "$@"\n', encoding="utf-8",
    )
    result = subprocess.run([bash_executable, str(copied), "--aifactory-env", "prod", "--project-only",
                             "--aifactory-version", "125"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "<--aifactory-env>", "<prod>", "<--project-only>", "<--aifactory-version>", "<125>",
    ]


@pytest.mark.parametrize("launcher", LAUNCHERS, ids=lambda path: path.name.split("-")[0])
def test_environment_help_and_bash_syntax(launcher, bash_executable):
    result = parse_launcher(launcher, ["--help"], {}, bash_executable)
    assert result.returncode == 0
    assert "--aifactory-env dev|stage|prod" in result.stdout
    assert "Dev OR Stage" in result.stdout
    result = subprocess.run([bash_executable, "-n", str(launcher)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_stable_launchers_keep_flag_and_guard_before_dispatch():
    for launcher in LAUNCHERS:
        source = launcher.read_text(encoding="utf-8")
        assert "# AIFACTORY_ENVIRONMENT_CONTRACT=1" in source
        assert source.index('environment_argument=""') < source.index("reviewed_project=false")
        assert 'exec bash "$stable_launcher" "${launcher_arguments[@]}"' in source
        assert 'for helper in project_deployment.py project_environment.py; do' in source
        assert 'cp "$deployment_dir/$helper" "$state_dir/lib/"' in source
        assert '"${promotion_arguments[@]}"' in source
        assert "check_project_environment" not in source
        assert 'export AIFACTORY_TARGET_ENVIRONMENT="$ENVIRONMENT"' not in source


@pytest.mark.parametrize("target", ["dev", "stage", "prod"])
def test_github_dispatch_uses_exact_environment(target, bash_executable):
    source = LAUNCHERS[1].read_text(encoding="utf-8")
    dispatch = source.split('\ngh workflow run "$WORKFLOW_FILE"', 1)[1].split('\nrun_id=""', 1)[0]
    secret = source.split('  gh secret set AIFACTORY_CONFIG_JSON', 1)[1].split("\nfi", 1)[0]
    script = (
        'set -euo pipefail\n'
        f'ENVIRONMENT={target}\n'
        'WORKFLOW_FILE=infra-project.yml github_repo=example/factory config_override_file=aifactory/variables.json\n'
        'RUNNER_LABEL=unit-runner CONFIG_FILE=/dev/null\n'
        'gh() { printf "<%s>\\n" "$@"; }\n'
        'gh secret set AIFACTORY_CONFIG_JSON' + secret +
        '\ngh workflow run "$WORKFLOW_FILE"' + dispatch
    )
    result = subprocess.run([bash_executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert f"<--env>\n<{target}>" in result.stdout
    assert f"<environment={target}>" in result.stdout


@pytest.fixture
def stubbed_launcher(tmp_path, bash_executable):
    root = tmp_path / "consumer"
    root.mkdir()
    (root / "aifactory").mkdir()
    (root / "lib").mkdir()
    (root / "ui").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "trace"
    copy_launcher_bundle(root)
    with (root / "ui/terminal.sh").open("a", encoding="utf-8", newline="\n") as library:
        library.write('\n# Workspace guard has separate scoped-creation tests.\n'
                      'aif_require_legacy_workspace() { [[ -d "$1/aifactory" ]]; }\n')
    values = {"project_number_000": "017", "tenantId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
              "dev_sub_id": "11111111-1111-1111-1111-111111111111",
              "test_sub_id": "22222222-2222-2222-2222-222222222222",
              "prod_sub_id": "33333333-3333-3333-3333-333333333333"}
    config = root / "aifactory/variables.json"
    config.write_text(json.dumps({"dev": values, "stage_prod": values}), encoding="utf-8")
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib.util, json, os, pathlib, sys\n"
        "spec = importlib.util.spec_from_file_location('copied_helper', sys.argv[1])\n"
        "helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)\n"
        "target = sys.argv[sys.argv.index('--aifactory-env')+1] if '--aifactory-env' in sys.argv else None\n"
        "try:\n"
        "    project, target, config, root = helper.deployment_inputs(os.environ, target)\n"
        "except ValueError as error:\n"
        "    sys.exit(str(error))\n"
        "assert pathlib.Path(sys.argv[1]).parent.parent.parent.name == '.aifactory-update-state'\n"
        "with open(os.environ['AIF_TEST_TRACE'], 'a', encoding='utf-8') as stream:\n"
        "    stream.write('helper:' + json.dumps({'project':project, 'target':target, 'config':config, "
        "'root':root, 'project_only':os.environ.get('AIFACTORY_PROJECT_ONLY'), "
        "'reviewed_target':os.environ.get('AIFACTORY_TARGET_ENVIRONMENT'), "
        "'route':sys.argv[sys.argv.index('--route')+1]}) + '\\n')\n",
        encoding="utf-8", newline="\n",
    )
    guard = tmp_path / "guard.sh"
    guard.write_text(r'''
git() { printf 'legacy:git:%s\n' "$*" >> "$AIF_TEST_TRACE"; exit 71; }
gh() { printf 'legacy:gh:%s\n' "$*" >> "$AIF_TEST_TRACE"; exit 71; }
az() { printf 'legacy:az:%s\n' "$*" >> "$AIF_TEST_TRACE"; exit 71; }
curl() { exit 99; }
wget() { exit 99; }
python() {
  if [[ "$1" == "--version" ]]; then printf 'Python 3\n'; return; fi
  case "$1" in
    */release_version.py)
      printf 'version:%s\n' "$*" >> "$AIF_TEST_TRACE"
      printf 'export AIFACTORY_VERSION=main AIF_SUBMODULE_BRANCH=main AIF_SUBMODULE_REF=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n'
      ;;
    */project_deployment.py)
      "$AIF_TEST_PYTHON" "$AIF_TEST_PROBE" "$@"
      ;;
    *) printf 'unexpected-python\n' >> "$AIF_TEST_TRACE"; exit 99 ;;
  esac
}
python3() { python "$@"; }
py() { [[ "$1" != "-3" ]] || shift; python "$@"; }
export -f git gh az curl wget python python3 py
''', encoding="utf-8", newline="\n")
    env = {key: value for key, value in os.environ.items() if key.upper() in ("SYSTEMROOT", "WINDIR", "COMSPEC")}
    env.update(HOME=home.as_posix(), USERPROFILE=str(home), PATH="/usr/bin:/bin",
               BASH_ENV=guard.as_posix(), AIF_TEST_TRACE=trace.as_posix(), AIF_TEST_PROBE=probe.as_posix(),
               AIF_TEST_PYTHON=sys.executable.replace("\\", "/"), AIFACTORY_USE_JSON_OVERRIDE="no")

    def run(route, args, extra=None):
        if trace.exists():
            trace.unlink()
        result = subprocess.run([bash_executable, "--noprofile", "--norc",
                                 str(root / f"{route}-update-aifactory-and-run-project.sh"), *args],
                                cwd=root, env={**env, **(extra or {})}, input="", capture_output=True,
                                text=True, timeout=30)
        lines = trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []
        assert "unexpected-python" not in lines
        return result, lines
    return run, root, home


@pytest.mark.parametrize("route", ["GH", "GHA", "ADO"])
@pytest.mark.parametrize("target", ["stage", "prod"])
@pytest.mark.parametrize("project_only", [False, True])
def test_full_stable_relaunch_selects_only_public_target(stubbed_launcher, route, target, project_only):
    run, root, home = stubbed_launcher
    args = ["--aifactory-env", target, "--aifactory-version", "125", "--resume-after-bootstrap"]
    if project_only:
        args.append("--project-only")
    result, trace = run(route, args)
    assert result.returncode == 0, result.stderr
    assert len(trace) == 2 and trace[0].startswith("version:")
    assert "--aifactory-version 125" in trace[0]
    assert ("--project-only" in trace[0]) == project_only
    selected = json.loads(trace[1].removeprefix("helper:"))
    assert selected == {"project": "017", "target": target, "config": str(root / "aifactory/variables.json"),
                        "root": str(root), "project_only": str(project_only).lower(),
                        "reviewed_target": None, "route": "ado" if route == "ADO" else "gha"}
    assert not list((home / ".aifactory-update-state").iterdir())


@pytest.mark.parametrize("route", ["GH", "GHA", "ADO"])
@pytest.mark.parametrize("args", [[], ["--aifactory-env", "dev"]])
@pytest.mark.parametrize("project_only", [False, True])
def test_full_legacy_dev_does_not_require_json(stubbed_launcher, route, args, project_only):
    run, root, _ = stubbed_launcher
    (root / "aifactory/variables.json").unlink()
    result, trace = run(route, [*args, *(["--project-only"] if project_only else [])])
    assert result.returncode == 71, result.stderr
    assert trace[0].startswith("version:") and trace[1].startswith("legacy:")
    assert "--aifactory-version main" not in trace[0]
    assert not any(line.startswith("helper:") for line in trace)


@pytest.mark.parametrize("route", ["GH", "ADO"])
def test_full_legacy_dev_rejects_incomplete_control_bundle(stubbed_launcher, route):
    run, root, _ = stubbed_launcher
    (root / "lib/project_environment.py").unlink()
    result, trace = run(route, ["--project-only"])
    assert result.returncode != 0
    assert "Complete dual-layout launcher bundle is not installed" in result.stderr
    assert trace == []


@pytest.mark.parametrize("route", ["GH", "ADO"])
@pytest.mark.parametrize("args,extra", [
    (["--aifactory-env", "stage"], {"AIFACTORY_TARGET_ENVIRONMENT": "prod"}),
    (["--aifactory-env", ""], {}),
    (["--aifactory-env", "qa"], {}),
    (["--aifactory-env", "stage", "--aifactory-env", "stage"], {}),
])
def test_full_invalid_flag_fails_before_stable_copy_or_commands(stubbed_launcher, route, args, extra):
    run, _, home = stubbed_launcher
    result, trace = run(route, args, extra)
    assert result.returncode == 1 and trace == []
    assert not (home / ".aifactory-update-state").exists()


@pytest.mark.parametrize("route", ["GH", "ADO"])
def test_full_reviewed_inputs_are_preserved_not_inferred_without_public_flag(stubbed_launcher, route):
    run, root, _ = stubbed_launcher
    result, trace = run(route, ["--project-only"], {"AIFACTORY_TARGET_ENVIRONMENT": "stage"})
    assert result.returncode == 1 and "All reviewed" in result.stderr
    assert len(trace) == 1 and trace[0].startswith("version:")
    selected = root / "aifactory/selected.json"
    shutil.copyfile(root / "aifactory/variables.json", selected)
    result, trace = run(route, ["--project-only", "--aifactory-env", "stage"], {
        "AIFACTORY_TARGET_ENVIRONMENT": "stage", "AIFACTORY_PROJECT_NUMBER": "017",
        "AIFACTORY_PROJECT_CONFIG": str(selected),
    })
    assert result.returncode == 0, result.stderr
    assert json.loads(trace[1].removeprefix("helper:"))["config"] == str(selected)


@pytest.mark.parametrize("route", ["GH", "ADO"])
def test_full_relaunch_copies_complete_helper_family_from_submodule_fallback(stubbed_launcher, route):
    run, root, _ = stubbed_launcher
    fallback = root / "azure-enterprise-scale-ml/bootstrap"
    fallback.mkdir(parents=True)
    shutil.move(str(root / "lib"), str(fallback / "lib"))
    shutil.move(str(root / "ui"), str(fallback / "ui"))
    for launcher in root.glob("*.sh"):
        shutil.copyfile(launcher, fallback / launcher.name)
    result, trace = run(route, ["--project-only", "--aifactory-env", "prod"])
    assert result.returncode == 0, result.stderr
    assert json.loads(trace[1].removeprefix("helper:"))["target"] == "prod"


def test_bootstrap_installs_all_promotion_dependencies_offline(tmp_path, bash_executable):
    source = (ROOT / "00-start.sh").read_text(encoding="utf-8")
    install = source.split("# Install the complete control bundle", 1)[1].split("\nif aif_registered_layout_root", 1)[0]
    install = install.split("\n", 1)[1]
    submodule = tmp_path / "azure-enterprise-scale-ml"
    copy_launcher_bundle(submodule / "bootstrap")
    dependencies = ("project_deployment.py", "project_environment.py", "release_version.py", "release_version.sh")
    result = subprocess.run([bash_executable, "--noprofile", "--norc", "-c",
                             'set -euo pipefail\nSCRIPT_DIR="$1"\n'
                             'source "$SCRIPT_DIR/bootstrap/lib/layout_router.sh"\n' + install,
                             "install", submodule.as_posix()],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert all((tmp_path / "lib" / name).read_bytes() == (ROOT / "bootstrap/lib" / name).read_bytes()
               for name in dependencies)
