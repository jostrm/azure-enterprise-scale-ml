"""Pure offline harness tests; the separate required CLI runs the real compiler."""
from __future__ import annotations

import itertools
import json
import math
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from base import config
from domain.bicep_matrix import (
    Case, Compiler, Feature, MatrixError, bicep_literal, discover_entrypoints,
    generate_cases, inventory_features, reachable_templates, required_bindings,
    required_flag_defaults, run_matrix, verify_cases, work_directory,
    public_registry_reference,
)


def features(count):
    return [Feature(f"enable{i}", "bool" if i % 2 else "string",
                    bool(i % 3) if i % 2 else str(bool(i % 3)).lower(), "bicep")
            for i in range(count)]


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 5, 16, 31, 44, 64, 129])
def test_deterministic_complete_matrix_without_exponential_enumeration(count):
    flags = features(count)
    cases = generate_cases(flags)
    assert cases == generate_cases(flags)
    assert verify_cases(flags, cases) == 4 * math.comb(count, 2)
    if count:
        assert len(cases) == 3 + count + 2 * math.ceil(math.log2(count))
    else:
        assert cases == [Case("baseline", {})]
    for a, b in itertools.combinations(flags, 2):
        assert {(case.values[a.name], case.values[b.name]) for case in cases} == {
            (a.value(x), b.value(y)) for x in (False, True) for y in (False, True)
        }


def test_inventory_uses_actual_defaults_and_discovers_new_flags_without_allowlist():
    params = {
        "enableNewFeature": {"type": "bool", "defaultValue": True},
        "disableOldFeature": {"type": "string", "defaultValue": "false"},
        "centralDnsZoneByPolicyInHub": {"type": "bool", "defaultValue": False},
        "unprefixedSwitch": {"type": "string", "allowedValues": ["false", "true"], "defaultValue": "true"},
        "region": {"type": "string", "defaultValue": "eastus"},
        "byoAseFullResourceId": {"type": "string", "defaultValue": ""},
        "useCommonSP_ID": {"type": "string", "defaultValue": ""},
    }
    flags = inventory_features(params)
    assert {f.name: f.default for f in flags} == {
        "enableNewFeature": True, "disableOldFeature": "false",
        "centralDnsZoneByPolicyInHub": False, "unprefixedSwitch": "true",
    }
    old_cases = generate_cases(flags)
    params["addFutureFeature"] = {"type": "bool", "defaultValue": False}
    updated = inventory_features(params)
    with pytest.raises(MatrixError, match="missing/extra flags"):
        verify_cases(updated, old_cases)
    verify_cases(updated, generate_cases(updated))


@pytest.mark.parametrize("schema", [
    {"type": "int", "defaultValue": 1},
    {"type": "string", "defaultValue": "sometimes"},
    {"type": "bool", "defaultValue": "true"},
    {"type": "bool", "defaultValue": 1},
    {"type": "bool"},
    {"type": "bool", "defaultValue": False, "allowedValues": [False]},
    {"type": "string", "defaultValue": "true", "allowedValues": ["true", "false", "auto"]},
    {"type": "bool", "defaultValue": "[equals(resourceGroup().name, 'x')]"},
])
def test_unsupported_or_invalid_flag_schema_fails_not_skips(schema):
    with pytest.raises(MatrixError):
        inventory_features({"enableFuture": schema})


def test_boolean_default_expression_is_strict_and_preserves_actual_default():
    flags = inventory_features({
        "enablePublicAccessWithPerimeter": {"type": "bool", "defaultValue": False},
        "enableDatafactoryManagedVnet": {
            "type": "bool", "defaultValue": "[not(parameters('enablePublicAccessWithPerimeter'))]",
        },
    })
    assert {f.name: f.default for f in flags} == {
        "enablePublicAccessWithPerimeter": False, "enableDatafactoryManagedVnet": True,
    }


@pytest.mark.parametrize("params", [
    {"enableA": {"type": "bool", "defaultValue": "[parameters('enableA')]"}},
    {"enableA": {"type": "bool", "defaultValue": "[parameters('missing')]"}},
    {"enableA": {"type": "bool", "defaultValue": "[not(parameters('enableB'))]"},
     "enableB": {"type": "string", "defaultValue": "true"}},
])
def test_cyclic_unknown_or_wrong_type_default_reference_is_error(params):
    with pytest.raises(MatrixError):
        inventory_features(params)


def test_required_flags_use_explicit_configured_default_only():
    params = {"addBastionHost": {"type": "bool"}}
    with pytest.raises(MatrixError, match="no declared/configured baseline"):
        inventory_features(params)
    assert inventory_features(params, {"addBastionHost": False}) == [
        Feature("addBastionHost", "bool", False, "ado-required-default"),
    ]
    ado, github = required_flag_defaults()
    assert set(ado) == set(github) == {"addBastionHost", "hybridBenefit"}
    assert all(type(value) is bool for value in (*ado.values(), *github.values()))


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_bool", "wrong_string", "integer_bool"])
def test_mutated_parameter_variants_are_rejected(mutation):
    flags = features(4)
    cases = generate_cases(flags)
    values = dict(cases[-1].values)
    if mutation == "missing":
        values.pop("enable0")
    elif mutation == "extra":
        values["enableNeverDeclared"] = True
    elif mutation == "wrong_bool":
        values["enable1"] = "false"
    elif mutation == "integer_bool":
        values["enable1"] = 0
    else:
        values["enable0"] = False
    cases[-1] = replace(cases[-1], values=values)
    with pytest.raises(MatrixError):
        verify_cases(flags, cases)


@pytest.mark.parametrize("name", ["baseline", "all_off", "all_on", "toggle_enable2"])
def test_missing_required_case_fails(name):
    flags = features(4)
    with pytest.raises(MatrixError):
        verify_cases(flags, [c for c in generate_cases(flags) if c.name != name])


def test_pair_coverage_checker_detects_missing_mixed_pair_even_with_all_individual_flips():
    flags = [Feature("enableA", "bool", False, "bicep"),
             Feature("enableB", "bool", True, "bicep")]
    cases = [c for c in generate_cases(flags) if not c.name.startswith("pair_bit")]
    with pytest.raises(MatrixError, match="Missing pair states"):
        verify_cases(flags, cases)


def test_duplicate_and_incorrect_baseline_cases_fail():
    flags = features(2)
    cases = generate_cases(flags)
    with pytest.raises(MatrixError, match="Duplicate"):
        verify_cases(flags, [*cases, cases[0]])
    cases[0] = Case("baseline", dict(cases[1].values))
    with pytest.raises(MatrixError, match="baseline"):
        verify_cases(flags, cases)


def test_synthetic_required_bindings_do_not_override_real_defaults():
    params = {
        "location": {"type": "string", "defaultValue": "[deployment().location]"},
        "identity": {"type": "string", "minLength": 3, "maxLength": 5},
        "secret": {"type": "securestring"},
        "tier": {"type": "string", "allowedValues": ["test", "prod"]},
        "tags": {"type": "object"},
        "names": {"type": "array"},
        "count": {"type": "int", "minValue": 4},
        "enableA": {"type": "bool"},
    }
    bound = required_bindings(params, {"enableA"})
    assert "location" not in bound and "enableA" not in bound
    assert 3 <= len(bound["identity"]) <= 5
    assert bound["tier"] == "test" and bound["count"] == 4
    assert bound["tags"] == {} and bound["names"] == []
    with pytest.raises(MatrixError, match="explicit fixture"):
        required_bindings({"names": {"type": "array", "minLength": 2}}, set())
    backend = required_bindings({"azureOpenAIBackends": {"type": "array", "minLength": 1}}, set())
    assert backend["azureOpenAIBackends"][0]["endpoint"] == "https://offline.invalid"
    with pytest.raises(MatrixError, match="no longer matches"):
        required_bindings({"azureOpenAIBackends": {"type": "array", "minLength": 2}}, set())


def test_bicep_literal_does_not_interpret_quoted_or_interpolated_strings():
    assert bicep_literal(True) == "true"
    assert bicep_literal("false") == "'false'"
    assert bicep_literal("a'${x}\\b") == "'a\\'\\${x}\\\\b'"
    assert bicep_literal({}) == "json('{}')"


def test_dynamic_production_entrypoints_include_common_genai_and_both_gateways():
    paths = discover_entrypoints(config.REPO_ROOT)
    relative = {p.relative_to(config.REPO_ROOT).as_posix() for p in paths}
    assert "environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep" in relative
    assert "environment_setup/aifactory/bicep/esml-genai-1/09-ai-foundry-2025-v4.bicep" in relative
    assert "environment_setup/aifactory/bicep/esml-common/ai-gateway/apim/main.bicep" in relative
    assert "environment_setup/aigateway/kong/main.bicep" in relative
    registry_modules = set()
    reachable = reachable_templates(paths, config.REPO_ROOT, registry_modules)
    assert set(paths) < set(reachable)


def test_reachable_module_inventory_ignores_comments_and_requires_explicit_registry_inventory():
    with work_directory(config.REPO_ROOT) as work:
        root = work / "root.bicep"
        child = work / "child.bicep"
        child.write_text("param enableChild bool = false\n", encoding="utf-8")
        root.write_text("// module skip './missing.bicep' = {}\n"
                        "/* module skip2 './missing.bicep' = {} */\n"
                        "module child './child.bicep' = {name: 'child'}\n", encoding="utf-8")
        assert set(reachable_templates([root], work)) == {root, child}
        root.write_text("module external 'br:example.invalid/x:v1' = {}\n", encoding="utf-8")
        with pytest.raises(MatrixError, match="explicitly inventoried"):
            reachable_templates([root], work)
        registry_modules = set()
        assert reachable_templates([root], work, registry_modules) == [root]
        assert registry_modules == {"br:example.invalid/x:v1"}
    assert not work.exists()


def test_entrypoint_inventory_adds_new_roots_and_fails_on_unresolved_references():
    with work_directory(config.REPO_ROOT) as repo:
        base = repo / "environment_setup" / "aifactory" / "bicep"
        source = base / "copy_to_local_settings"
        github = source / "github-actions"
        github.mkdir(parents=True)
        (source / "azure-devops").mkdir()
        template = base / "esml-genai-1" / "future.bicep"
        template.parent.mkdir()
        template.write_text("param enableFuture bool = true\n", encoding="utf-8")
        pipeline = github / "infra-future.yml"
        pipeline.write_text('--template-file "esml-genai-1/future.bicep"\n', encoding="utf-8")
        assert discover_entrypoints(repo) == [template]
        pipeline.write_text('--template-file "$DYNAMIC_TEMPLATE"\n', encoding="utf-8")
        with pytest.raises(MatrixError, match="Unresolved"):
            discover_entrypoints(repo)
        pipeline.write_text('--template-file "esml-genai-1/missing.bicep"\n', encoding="utf-8")
        with pytest.raises(MatrixError, match="Missing"):
            discover_entrypoints(repo)


def test_missing_bicep_is_a_failed_gate_with_report_not_a_skip():
    nonexistent = str(config.REPO_ROOT / "does-not-exist-bicep")
    with pytest.raises(MatrixError, match="required but not found"):
        Compiler(nonexistent, config.REPO_ROOT)
    report = run_matrix(config.REPO_ROOT, nonexistent)
    assert report["status"] == "failed"
    assert report["errors"] and report["counts"]["bound_cases"] == 0


@pytest.mark.parametrize("entrypoint", ["module", "script"])
@pytest.mark.parametrize("prepare", [False, True])
def test_cli_entrypoints_return_nonzero_and_write_failure_report(entrypoint, prepare):
    suite = Path(__file__).resolve().parents[1]
    command = ([sys.executable, "-m", "domain.bicep_matrix"] if entrypoint == "module"
               else [sys.executable, str(suite / "run_bicep_matrix.py")])
    with work_directory(config.REPO_ROOT) as work:
        report_path = work / "missing-compiler.json"
        result = subprocess.run(
            [*command, "--bicep", str(work / "missing-bicep"), "--report", str(report_path),
             *(["--prepare-cache"] if prepare else [])],
            cwd=suite if entrypoint == "module" else config.REPO_ROOT,
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=30,
        )
        assert result.returncode == 1
        assert "required but not found" in result.stderr
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "failed"
        assert report["mode"] == ("public-cache-preparation" if prepare else "offline-validation")
        assert report["counts"]["compiler_invocations"] == 0


@pytest.mark.parametrize("reference", [
    "br/public:avm/res/web/site:0.21.0",
    "br:mcr.microsoft.com/bicep/avm/res/web/site:0.21.0",
])
def test_public_cache_dependency_normalization_uses_only_microsoft_registry(reference):
    assert public_registry_reference(reference) == "br:mcr.microsoft.com/bicep/avm/res/web/site:0.21.0"


@pytest.mark.parametrize("reference", [
    "br:private.example/module:1.0.0",
    "br/public:avm/res/web/site:latest",
    "br:mcr.microsoft.com.attacker.invalid/bicep/avm/res/web/site:0.21.0",
    "br/public:avm/../../private:0.1.0",
    "ts:00000000-0000-0000-0000-000000000000/group/spec:1.0",
])
def test_public_cache_dependency_preparation_rejects_private_unpinned_or_unknown_modules(reference):
    with pytest.raises(MatrixError, match="pinned public"):
        public_registry_reference(reference)
