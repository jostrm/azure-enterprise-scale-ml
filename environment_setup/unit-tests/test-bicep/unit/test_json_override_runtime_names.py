"""aif-149 (2026-11-06, infra-common run 42144864605): the JSON override wrote use_ad_groups=true, but the workflow's
step read env.useAdGroups (job env "useAdGroups: ${{ vars.USE_AD_GROUPS }}"), so 11-rgCommon got useAdGroups="" and
assigned the team group as a User (UnmatchedPrincipalType). A configuration key also reaches every workflow env name
that is bound to the matching GitHub variable (USE_AD_GROUPS for use_ad_groups), whatever its case."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py"
COMMON = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-common.yml"
spec = importlib.util.spec_from_file_location("json_overrides_runtime", SCRIPT)
overrides = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overrides)


def written(path):
    text, values, lines = path.read_text(encoding="utf-8"), {}, None
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        name, delimiter = lines[index].split("<<", 1)
        values[name] = lines[index + 1]
        index += 3
    return values


def test_a_lowercase_key_reaches_the_workflow_name_bound_to_its_variable(tmp_path, monkeypatch):
    env = tmp_path / "github_env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_ENV", str(env))
    applied, _ = overrides.apply({"use_ad_groups": "true", "admin_location": "swedencentral"}, "github", str(COMMON))
    values = written(env)
    assert applied == 2
    assert values["use_ad_groups"] == "true" and values["useAdGroups"] == "true"
    assert values["admin_location"] == "swedencentral"


def test_the_mapping_is_keyed_by_variable_name_whatever_the_case(tmp_path):
    workflow = tmp_path / "w.yml"
    workflow.write_text('jobs:\n  a:\n    env:\n      useAdGroups: "${{ vars.USE_AD_GROUPS }}"\n'
                        '      tags: "${{ vars.TAGS }}"\n', encoding="utf-8")
    names = overrides.github_runtime_names(str(workflow))
    assert overrides.runtime_names(names, "use_ad_groups") == {"useAdGroups"}
    assert overrides.runtime_names(names, "USE_AD_GROUPS") == {"useAdGroups"}
    assert overrides.runtime_names(names, "tags") == {"tags"}
    assert overrides.runtime_names(names, "unrelated") == set()
