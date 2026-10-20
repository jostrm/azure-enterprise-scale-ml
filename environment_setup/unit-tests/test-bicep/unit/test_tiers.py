"""Offline contracts for numbered unit-test tiers: manifest, selection, pytest glue and run_ci."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from base.tiers import ENVIRONMENT_VARIABLE, Tier, TierManifest
import run_ci
from tiers import MANIFEST


SUITE = run_ci.SUITE


def offline_test_files() -> set[str]:
    return {
        path.relative_to(SUITE).as_posix()
        for path in [*(SUITE / "unit").glob("test_*.py"), *SUITE.glob("test_*.py")]
    }


def small_manifest() -> TierManifest:
    return TierManifest(default="1-2", tiers=(
        Tier(1, "core", "Core.", ("unit/test_a.py",)),
        Tier(2, "pipelines", "Pipelines.", ("unit/test_b.py",)),
        Tier(3, "capacity", "Capacity.", ("unit/test_c.py",)),
    ))


def test_every_offline_test_file_belongs_to_exactly_one_tier():
    listed = [path for tier in MANIFEST.tiers for path in tier.files]
    assert len(listed) == len(set(listed)), "A test file is listed in more than one tier."
    unclassified = sorted(offline_test_files() - set(listed))
    assert not unclassified, f"Add each new test file to a tier in tiers.py: {unclassified}"
    missing = sorted(set(listed) - offline_test_files())
    assert not missing, f"tiers.py lists test files that no longer exist: {missing}"


def test_tiers_are_numbered_one_to_five_from_core_to_capacity():
    assert [(tier.number, tier.name) for tier in MANIFEST.tiers] == [
        (1, "core"), (2, "pipelines"), (3, "infra"), (4, "lifecycle"), (5, "capacity"),
    ]
    assert all(tier.summary and tier.files for tier in MANIFEST.tiers)


def test_preflight_and_capacity_suites_are_tier_five_and_skipped_by_default():
    for path in (
        "unit/test_capacity_preflight.py", "unit/test_capacity_resource_deployment.py",
        "unit/test_ai_search_capacity_retry.py", "unit/test_logic_app_plan_retry.py",
        "unit/test_preflight_peerability.py", "unit/test_region_reports.py",
        "unit/test_subnet_scaling_capacity.py",
    ):
        assert MANIFEST.tier_of(path) == 5, path
    assert MANIFEST.parse(MANIFEST.default) == frozenset({1, 2, 3, 4})


def test_key_vault_principal_guard_runs_on_every_push_with_identity_tests():
    # It drives the preflight, but a placeholder object ID leaves the vaults without an admin policy.
    assert MANIFEST.tier_of("unit/test_kv_principal_preflight.py") == 3
    assert MANIFEST.tier_of("unit/test_kv_access_policy_principals.py") == 3


def test_this_contract_and_the_ci_runner_contract_are_core():
    assert MANIFEST.tier_of("unit/test_tiers.py") == 1
    assert MANIFEST.tier_of("unit/test_ci_runner.py") == 1


@pytest.mark.parametrize("spec,expected", [
    ("1-4", {1, 2, 3, 4}), ("5", {5}), ("1,5", {1, 5}), (" 2 - 3 , 5 ", {2, 3, 5}),
    ("all", {1, 2, 3, 4, 5}), ("ALL", {1, 2, 3, 4, 5}), ("1-5", {1, 2, 3, 4, 5}), ("3-3", {3}),
    ("default", {1, 2, 3, 4}),
])
def test_selection_accepts_numbers_ranges_lists_and_all(spec, expected):
    assert MANIFEST.parse(spec) == frozenset(expected)


@pytest.mark.parametrize("spec", ["0", "6", "1-6", "4-2", "x", "1,,2", "1-", "-2", "1-2-3", "core"])
def test_unknown_selection_fails_with_the_accepted_forms(spec):
    with pytest.raises(ValueError, match=r"tiers 1-5.*1-4.*1,5.*all"):
        MANIFEST.parse(spec)


def test_option_wins_over_environment_which_wins_over_the_manifest_default():
    manifest = small_manifest()
    assert manifest.resolve("3", {ENVIRONMENT_VARIABLE: "2"}).tiers == {3}
    assert manifest.resolve("3", {ENVIRONMENT_VARIABLE: "2"}).source == "option"
    assert manifest.resolve(None, {ENVIRONMENT_VARIABLE: "2"}).tiers == {2}
    assert manifest.resolve(None, {ENVIRONMENT_VARIABLE: "2"}).source == "environment"
    for option, environment in ((None, {}), ("", {ENVIRONMENT_VARIABLE: " "}), ("default", {})):
        selection = manifest.resolve(option, environment)
        assert (selection.tiers, selection.source, selection.spec) == ({1, 2}, "default", "1-2")
    assert manifest.resolve(None, {ENVIRONMENT_VARIABLE: "default"}).source == "default"


def test_selection_spec_is_normalized_for_reports():
    manifest = small_manifest()
    assert manifest.resolve("3, 1-2", {}).spec == "all"
    assert manifest.resolve("1,3", {}).spec == "1,3"
    assert MANIFEST.resolve("5,1-3", {}).spec == "1-3,5"
    assert MANIFEST.resolve(None, {}).skipped == (5,)


def test_default_selection_still_runs_a_file_that_was_named_explicitly():
    manifest = small_manifest()
    default = manifest.resolve(None, {})
    assert manifest.keeps("unit/test_a.py", default)
    assert not manifest.keeps("unit/test_c.py", default)
    assert manifest.keeps("unit/test_c.py", default, explicit=True)
    chosen = manifest.resolve("1", {})
    assert not manifest.keeps("unit/test_c.py", chosen, explicit=True)
    assert manifest.keeps("integration/test_live.py", chosen), "Unclassified files are never hidden."


def test_a_given_default_selection_also_filters_named_files():
    # Same contract as the config wizard's tests/tier_selection.py: only an absent value is implicit.
    manifest = small_manifest()
    for option, environment in (("default", {}), (None, {ENVIRONMENT_VARIABLE: "Default"})):
        selection = manifest.resolve(option, environment)
        assert (selection.source, selection.explicit) == ("default", True)
        assert not manifest.keeps("unit/test_c.py", selection, explicit=True)
    assert manifest.resolve(None, {}).explicit is False


@pytest.mark.parametrize("tiers,problem", [
    ((Tier(1, "a", "A.", ("x.py",)), Tier(3, "b", "B.", ("y.py",))), "numbered 1-"),
    ((Tier(1, "a", "A.", ("x.py",)), Tier(2, "a", "B.", ("y.py",))), "name"),
    ((Tier(1, "a", "A.", ("x.py",)), Tier(2, "b", "B.", ("x.py",))), "x.py"),
])
def test_manifest_rejects_gaps_duplicate_names_and_files_in_two_tiers(tiers, problem):
    with pytest.raises(ValueError, match=problem):
        TierManifest(default="1", tiers=tiers)


def test_manifest_rejects_an_invalid_default():
    with pytest.raises(ValueError, match="tiers 1-1"):
        TierManifest(default="2", tiers=(Tier(1, "a", "A.", ("x.py",)),))


def collect(*arguments: str, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    child = {key: value for key, value in os.environ.items()
             if key not in {ENVIRONMENT_VARIABLE, "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}}
    child.update(environment or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *arguments],
        cwd=SUITE, env=child, capture_output=True, text=True, encoding="utf-8", timeout=300, check=False,
    )


CAPACITY = "unit/test_preflight_peerability.py"
CORE = "unit/test_scenario_matrix.py"


def collected_files(result: subprocess.CompletedProcess) -> set[str]:
    return {line.split("::", 1)[0] for line in result.stdout.splitlines() if "::" in line}


def test_pytest_option_deselects_tiers_outside_the_selection():
    result = collect("--tiers", "1-4", CAPACITY, CORE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert collected_files(result) == {CORE}
    assert "deselected" in result.stdout


def test_pytest_environment_variable_selects_tiers():
    result = collect(CAPACITY, CORE, environment={ENVIRONMENT_VARIABLE: "5"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert collected_files(result) == {CAPACITY}


def test_pytest_default_runs_explicitly_named_capacity_file():
    result = collect(CAPACITY)
    assert result.returncode == 0, result.stdout + result.stderr
    assert collected_files(result) == {CAPACITY}


def test_pytest_tier_markers_are_registered_and_applied():
    result = collect("--tiers", "all", "-m", "tier5", "--strict-markers", CAPACITY, CORE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert collected_files(result) == {CAPACITY}


def test_pytest_rejects_an_unknown_selection_as_a_usage_error():
    result = collect("--tiers", "9", CORE)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "tiers 1-5" in result.stderr


def run_unit_phase(tmp_path, monkeypatch, *arguments: str, environment: dict[str, str] | None = None):
    calls = []

    def passed(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)
    for key, value in (environment or {}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(run_ci.subprocess, "run", passed)
    monkeypatch.setattr(run_ci, "find_bash", lambda: "bash")
    code = run_ci.main(["--phase", "unit", "--results-dir", str(tmp_path), *arguments])
    summary = json.loads((tmp_path / "unit-summary.json").read_text(encoding="utf-8"))
    return code, calls[0], summary


def test_run_ci_passes_the_default_selection_to_pytest_and_reports_it(tmp_path, monkeypatch):
    code, command, summary = run_unit_phase(tmp_path, monkeypatch)
    assert code == 0
    assert command[command.index("--tiers") + 1] == "1-4"
    assert summary["tiers"] == {"selected": "1-4", "source": "default", "skipped": [5]}


def test_run_ci_option_and_environment_enable_tier_five(tmp_path, monkeypatch):
    _, command, summary = run_unit_phase(tmp_path, monkeypatch, "--tiers", "all")
    assert command[command.index("--tiers") + 1] == "all"
    assert summary["tiers"] == {"selected": "all", "source": "option", "skipped": []}
    _, command, summary = run_unit_phase(tmp_path, monkeypatch, environment={ENVIRONMENT_VARIABLE: "5"})
    assert command[command.index("--tiers") + 1] == "5"
    assert summary["tiers"]["source"] == "environment"


def test_unknown_selection_message_does_not_echo_the_raw_value():
    with pytest.raises(ValueError) as error:
        MANIFEST.parse("##vso[task.setvariable]x")
    assert "##vso" not in str(error.value)


def test_a_bad_tier_value_cannot_fail_the_syntax_or_bicep_phases(tmp_path, monkeypatch):
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, "1-9")
    monkeypatch.setattr(run_ci, "find_bash", lambda: "bash")
    monkeypatch.setattr(run_ci, "check_syntax", lambda root, bash: {"checked": {}, "failures": []})
    assert run_ci.main(["--phase", "syntax", "--results-dir", str(tmp_path)]) == 0
    summary = json.loads((tmp_path / "syntax-summary.json").read_text(encoding="utf-8"))
    assert "tiers" not in summary


def test_run_ci_rejects_an_unknown_selection_before_running_tests(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_ci.subprocess, "run", lambda *a, **k: pytest.fail("pytest must not start"))
    with pytest.raises(SystemExit) as error:
        run_ci.main(["--phase", "unit", "--tiers", "9", "--results-dir", str(tmp_path)])
    assert error.value.code == 2
    assert "tiers 1-5" in capsys.readouterr().err


def test_readme_documents_every_tier_and_how_to_enable_tier_five():
    readme = (SUITE / "README.md").read_text(encoding="utf-8")
    for tier in MANIFEST.tiers:
        assert f"| {tier.number} | `{tier.name}` |" in readme
    for text in ("--tiers all", f"{ENVIRONMENT_VARIABLE}=all", "gh variable set AIF_TEST_TIERS"):
        assert text in readme
