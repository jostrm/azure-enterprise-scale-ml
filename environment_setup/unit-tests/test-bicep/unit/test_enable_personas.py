"""Compatibility flag contracts across deployed configuration entry points."""
import copy
import importlib.util
import json
import sys
from unittest.mock import Mock

import pytest
import yaml

from .test_persona_pipeline import ROOT, BICEP, TEMPLATES, inputs, manifest_file, pipeline
from .test_registered_personas import core, serializer, registered_creation
from .test_bootstrap_scaleset import state


@pytest.mark.parametrize("values,expected", [
    ({}, "legacy"),
    ({"persona_access_mode": "groups-v1"}, "groups-v1"),
    ({"enablePersonas": True, "persona_access_mode": "legacy"}, "groups-v1"),
    ({"enablePersonas": False, "persona_access_mode": "groups-v1"}, "legacy"),
    ({"ENABLE_PERSONAS": "true"}, "groups-v1"),
    ({"ENABLE_PERSONAS": "false", "PERSONA_ACCESS_MODE": "groups-v1"}, "legacy"),
    ({"ENABLEPERSONAS": "false"}, "legacy"),
])
def test_shared_mode_precedence(values, expected, tmp_path):
    config = {**inputs(), **values}
    if "persona_access_mode" not in values:
        config.pop("persona_access_mode")
    manifest_file(tmp_path, config)
    assert pipeline.configuration(config, "dev", tmp_path)[0] == expected
    assert core.mode(values) == expected
    assert serializer.persona_mode(values) == expected


@pytest.mark.parametrize("flag", [None, "", "yes", "0", "1", 0, 1, [], {}, "FALSE ", "False"])
@pytest.mark.parametrize("key", ["enablePersonas", "ENABLE_PERSONAS"])
def test_invalid_flag_fails_before_cloud(flag, key, tmp_path):
    values = {**inputs(), key: flag}
    cli = Mock()
    with pytest.raises(ValueError, match="enablePersonas"):
        pipeline.run(values, "dev", tmp_path, "project", "preflight", cli)
    cli.assert_not_called()
    with pytest.raises(ValueError, match="enablePersonas"):
        core.mode(values)
    with pytest.raises(ValueError, match="enablePersonas"):
        serializer.persona_mode(values)


@pytest.mark.parametrize("phase", ["validate", "preflight", "apply"])
def test_false_preserves_legacy_fields_and_exports_consistent_mode(phase, tmp_path):
    values = {**inputs(), "enablePersonas": False, "groups_project_members_genai_1": "old-group"}
    original = copy.deepcopy(values)
    report = pipeline.run(values, "dev", tmp_path, "project", phase, Mock(return_value=False))
    assert report["mode"] == "legacy"
    assert values == original
    assert not set(pipeline.HUMAN_CHANNELS).intersection(report["variables"])
    assert report["variables"]["enablePersonas"] == report["variables"]["ENABLE_PERSONAS"] == "false"
    assert report["variables"]["persona_access_mode"] == report["variables"]["PERSONA_ACCESS_MODE"] == "legacy"


def test_true_cannot_skip_manifest_or_marker_guard(tmp_path):
    cli = Mock()
    values = {**inputs(), "enablePersonas": True, "persona_access_mode": "legacy"}
    with pytest.raises(ValueError, match="manifest"):
        pipeline.run(values, "dev", tmp_path, "project", "preflight", cli)
    cli.assert_not_called()
    values["enablePersonas"] = False
    cli.side_effect = [True, {"tags": {pipeline.MARKER: "groups-v1"}}]
    with pytest.raises(ValueError, match="refusing downgrade"):
        pipeline.run(values, "dev", tmp_path, "project", "preflight", cli)


def test_true_exports_flag_and_derived_mode(tmp_path, monkeypatch):
    values = {**inputs(), "enablePersonas": True, "persona_access_mode": "legacy"}
    manifest_file(tmp_path, values)
    monkeypatch.setattr(pipeline.groups, "resolve_seeded_groups", Mock(return_value={}))
    output = pipeline.run(values, "dev", tmp_path, "project", "preflight", Mock(return_value=False))["variables"]
    assert output["enablePersonas"] == output["ENABLE_PERSONAS"] == "true"
    assert output["persona_access_mode"] == output["PERSONA_ACCESS_MODE"] == "groups-v1"
    assert all(output[key] == "" for key in pipeline.HUMAN_CHANNELS)


@pytest.mark.parametrize("flag", [False, True])
def test_bootstrap_generator_uses_flag_instead_of_stale_mode(flag):
    values = serializer.common_values({
        **state(), "enablePersonas": flag, "persona_access_mode": "legacy" if flag else "groups-v1",
        "persona_access_manifest": "access/personas.json",
    })
    assert values["enablePersonas"] is flag
    assert values["persona_access_mode"] == ("groups-v1" if flag else "legacy")
    assert bool(values["groups_project_members_genai_1"]) is not flag


def test_copy_refresh_preserves_old_opt_in_and_environment_overlays(tmp_path):
    active, template = tmp_path / "variables.json", tmp_path / "template.json"
    active.write_text(json.dumps({"dev": {"persona_access_mode": "groups-v1"},
                                  "stage_prod": {"persona_access_mode": "legacy"}}))
    template.write_text(json.dumps({"dev": {"enablePersonas": False, "persona_access_mode": "legacy"},
                                    "stage_prod": {"enablePersonas": False}}))
    serializer.merge_json_template(template, active)
    document = json.loads(active.read_text())
    assert core.mode(core.selected_config(document, "dev")) == "groups-v1"
    assert core.mode(core.selected_config(document, "prod")) == "legacy"
    for extension, merge, old, new in [
        ("yaml", serializer.merge_yaml_template, 'variables:\n  persona_access_mode: "groups-v1"\n',
         'variables:\n  enablePersonas: false\n  persona_access_mode: "legacy"\n'),
        ("env", serializer.merge_env_template, "PERSONA_ACCESS_MODE=groups-v1\n",
         "ENABLE_PERSONAS=false\nPERSONA_ACCESS_MODE=legacy\n"),
    ]:
        active, template = tmp_path / ("active." + extension), tmp_path / ("template." + extension)
        active.write_text(old)
        template.write_text(new)
        merge(template, active)
        assert ("enablePersonas: true" if extension == "yaml" else "ENABLE_PERSONAS=true") in active.read_text()


@pytest.mark.parametrize("flag", [False, True])
def test_json_override_flag_controls_runtime_environment_and_outputs(flag, tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("flag_overrides", BICEP / "scripts/apply-json-config-overrides.py")
    overrides = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overrides)
    values = {**inputs(), "enablePersonas": flag, "persona_access_mode": "legacy" if flag else "groups-v1"}
    manifest_file(tmp_path, values)
    path = tmp_path / "variables.json"
    path.write_text(json.dumps({"dev": values}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["overrides", "--file", str(path), "--environment", "dev", "--format", "azure-devops"])
    overrides.main()
    output = capsys.readouterr().out
    assert f"variable=enablePersonas]{str(flag).lower()}" in output
    assert f"variable=ENABLE_PERSONAS]{str(flag).lower()}" in output
    assert f"variable=persona_access_mode]{'groups-v1' if flag else 'legacy'}" in output
    assert f"variable=technical_admins_ad_object_id]{'' if flag else 'old-admin'}\n" in output
    assert ("variable=dev_test_prod]dev" in output) is flag


def test_templates_and_ci_bindings_offer_flag_without_breaking_absent_old_configs():
    defaults = json.loads((BICEP.parent / "variables.json").read_text())
    assert defaults["dev"]["enablePersonas"] is False
    ado = TEMPLATES / "azure-devops/esml-yaml-pipelines/variables"
    assert yaml.safe_load((ado / "variables.yaml").read_text())["variables"]["enablePersonas"] is False
    assert yaml.safe_load((ado / "persona-access-steps.yaml").read_text())["steps"][0]["env"]["ENABLE_PERSONAS"] == "$(enablePersonas)"
    assert "\nENABLE_PERSONAS=false\n" in (TEMPLATES / "github-actions/.env.template").read_text()
    for name in ("infra-common.yml", "infra-project-phase.yml"):
        for job in yaml.safe_load((TEMPLATES / "github-actions" / name).read_text(encoding="utf-8"))["jobs"].values():
            assert job["env"]["ENABLE_PERSONAS"] == "${{ vars.ENABLE_PERSONAS || '' }}"
    assert '"ENABLE_PERSONAS"' in (TEMPLATES / "github-actions/03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")


def test_registered_creation_flag_cannot_bypass_unsupported_api(tmp_path, monkeypatch):
    manifest_file(tmp_path, inputs())
    monkeypatch.setattr(registered_creation.sys.stdin, "isatty", lambda: False)
    args = registered_creation.parser().parse_args(["gha", "--save-receipt", str(tmp_path / "review.json")])
    request = registered_creation.creation_input(args, tmp_path, "main", {
        "AIF_TENANT_ID": inputs()["tenantId"], "AIF_DEV_SUBSCRIPTION_ID": inputs()["dev_sub_id"],
        "AIF_PREFIX": "acme-", "AIF_LOCATION": "westeurope", "GITHUB_REPOSITORY": "org/repo",
        "AIF_ENABLE_PERSONAS": "true", "AIF_PERSONA_ACCESS_MODE": "legacy",
        "AIF_PERSONA_ACCESS_MANIFEST": "access/personas.json",
    })
    assert request["config"]["enablePersonas"] is True
    assert request["config"]["persona_access_mode"] == "groups-v1"
    monkeypatch.setattr(registered_creation, "creation_input", lambda *args: request)
    monkeypatch.setattr(core, "seeds", Mock(return_value={}))
    client = Mock()
    client.request.return_value = {"operation_mode": "configuration", "capabilities": ["initial-project-v1"]}
    receipt = Mock()
    monkeypatch.setattr(registered_creation, "load_sdk", lambda: (lambda: client, receipt))
    monkeypatch.delenv("AIF_DRY_RUN", raising=False)
    with pytest.raises(ValueError, match="persona-groups-v1"):
        registered_creation.prepare(args, tmp_path, "main")
    receipt.assert_not_called()


def test_registered_flag_freezes_personas_and_rejects_false_worker_downgrade(tmp_path, monkeypatch):
    from .test_registered_personas import deployment
    document, manifest = deployment(tmp_path)
    document["config"]["dev"].update(enablePersonas=True, persona_access_mode="legacy")
    monkeypatch.setattr(core, "remote_manifest", Mock(return_value=manifest))
    monkeypatch.setattr(pipeline.groups, "resolve_seeded_groups", Mock(return_value={}))
    monkeypatch.setattr(pipeline, "azure_cli", Mock(return_value=False))
    provision = Mock()
    monkeypatch.setattr(pipeline.access, "provision", provision)
    core.freeze(Mock(), document, document["deployment"], ROOT)
    assert document["deployment"]["persona_access"]["mode"] == "groups-v1"
    assert document["deployment"]["steps"][0]["parameters"]["projectMembers"] == []
    document["config"]["dev"]["enablePersonas"] = False
    with pytest.raises(ValueError, match="cannot be downgraded"):
        core.worker(document, ROOT, execute=True)
    provision.assert_not_called()


@pytest.mark.parametrize("selected,expected", [
    ({"persona_access_mode": "groups-v1"}, "groups-v1"),
    ({"enablePersonas": True, "persona_access_mode": "legacy"}, "groups-v1"),
    ({"enablePersonas": False, "persona_access_mode": "groups-v1"}, "legacy"),
    ({"ENABLE_PERSONAS": "true", "persona_access_mode": "legacy"}, "groups-v1"),
])
def test_config_file_overrides_conflicting_ci_defaults(selected, expected, tmp_path, monkeypatch, capsys):
    values = {**inputs(), **selected}
    manifest_file(tmp_path, values)
    config = tmp_path / "variables.json"
    config.write_text(json.dumps({"dev": values}))
    monkeypatch.setenv("ENABLE_PERSONAS", "false")
    monkeypatch.setenv("ENABLEPERSONAS", "false")
    monkeypatch.setattr(sys, "argv", ["personas", "--config", str(config), "--repo-root", str(tmp_path),
                                     "--environment", "dev", "--scope", "project", "--phase", "validate"])
    assert pipeline.main() == 0
    assert json.loads(capsys.readouterr().out)["mode"] == expected


@pytest.mark.parametrize("flag,expected", [("false", "legacy"), ("true", "groups-v1"),
                                          ("", None), ("yes", None), ("__absent__", None)])
def test_shell_bootstrap_flag_is_strict_before_any_mutation(tmp_path, flag, expected):
    import shlex
    from .test_simple_bootstrap import bash, LIB
    result = bash(
        f"AIF_PYTHON=({shlex.quote(sys.executable)}); "
        f"AIF_SCALESET_LIB_DIR={shlex.quote(str(LIB))}; AIF_REPO_ROOT={shlex.quote(str(tmp_path))}; "
        f"AIF_ENABLE_PERSONAS={shlex.quote(flag)}; AIF_PERSONA_ACCESS_MODE=legacy; "
        "AIF_PERSONA_ACCESS_MANIFEST=access/personas.json; "
        'aif_load_persona_configuration; printf "SELECTED:%s" "$AIF_PERSONA_ACCESS_MODE"',
        "aif_load_persona_configuration",
    )
    if expected:
        assert result.returncode == 0, result.stderr
        assert result.stdout.endswith("SELECTED:" + expected)
    else:
        assert result.returncode != 0 and "enablePersonas" in result.stderr
        assert "SELECTED" not in result.stdout


def test_json_unrelated_override_does_not_disable_ci_persona_selection(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("flag_overrides_absent", BICEP / "scripts/apply-json-config-overrides.py")
    overrides = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overrides)
    path = tmp_path / "variables.json"
    path.write_text(json.dumps({"dev": {"technical_admins_ad_object_id": "old-admin"}}))
    monkeypatch.setenv("ENABLE_PERSONAS", "true")
    monkeypatch.setattr(sys, "argv", ["overrides", "--file", str(path), "--environment", "dev", "--format", "azure-devops"])
    overrides.main()
    output = capsys.readouterr().out
    assert "variable=enablePersonas]" not in output
    assert "variable=ENABLE_PERSONAS]" not in output
    assert "variable=persona_access_mode]" not in output


@pytest.mark.parametrize("alias", ["enablePersonas", "ENABLEPERSONAS", "ENABLE_PERSONAS"])
@pytest.mark.parametrize("mode", ["legacy", "groups-v1", "groups-v2"])
def test_cli_empty_ci_flag_preserves_and_validates_old_mode(alias, mode, tmp_path, monkeypatch, capsys):
    for key in ("enablePersonas", "ENABLEPERSONAS", "ENABLE_PERSONAS"):
        monkeypatch.delenv(key, raising=False)
    values = {**inputs(), "persona_access_mode": mode}
    manifest_file(tmp_path, values)
    for key, value in values.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setenv(alias, "")
    cli = Mock(side_effect=AssertionError("Validation must remain offline"))
    monkeypatch.setattr(pipeline, "azure_cli", cli)
    monkeypatch.setattr(sys, "argv", ["personas", "--repo-root", str(tmp_path),
                                     "--environment", "dev", "--scope", "project", "--phase", "validate"])
    result = pipeline.main()
    output = capsys.readouterr()
    if mode == "groups-v2":
        assert result == 1
        assert "Unsupported persona_access_mode 'groups-v2'" in output.err
        assert not output.out
    else:
        assert result == 0, output.err
        assert json.loads(output.out)["mode"] == mode
    cli.assert_not_called()


@pytest.mark.parametrize("alias", ["enablePersonas", "ENABLEPERSONAS", "ENABLE_PERSONAS"])
def test_cli_empty_json_flag_stays_invalid(alias, tmp_path, monkeypatch, capsys):
    values = {**inputs(), alias: ""}
    config = tmp_path / "variables.json"
    config.write_text(json.dumps({"dev": values}))
    monkeypatch.setenv("ENABLE_PERSONAS", "")
    cli = Mock(side_effect=AssertionError("Invalid flag must fail before cloud access"))
    monkeypatch.setattr(pipeline, "azure_cli", cli)
    monkeypatch.setattr(sys, "argv", ["personas", "--config", str(config), "--repo-root", str(tmp_path),
                                     "--environment", "dev", "--scope", "project", "--phase", "validate"])
    assert pipeline.main() == 1
    assert "enablePersonas must be a boolean" in capsys.readouterr().err
    cli.assert_not_called()


@pytest.mark.parametrize("environment", ["stage", "test", "prod"])
@pytest.mark.parametrize("section", ["stage_prod", "exact"])
@pytest.mark.parametrize("alias", ["ENABLEPERSONAS", "ENABLE_PERSONAS"])
@pytest.mark.parametrize("flag", [True, False, "true", "false", "yes", ""])
def test_persona_alias_overlays_agree_across_consumers(environment, section, alias, flag):
    from .test_template_flag_sync import load_override
    target = ("test" if environment == "stage" else environment) if section == "exact" else section
    document = {"dev": {"enablePersonas": flag not in (True, "true"), "untouched": {"keep": [1]}},
                "stage_prod": {}, target: {alias: flag}}
    original = copy.deepcopy(document)
    selections = (
        (pipeline.select_config(document, environment), pipeline.access_mode),
        (core.selected_config(document, environment), core.mode),
        (serializer.selected_persona_values(document, environment), serializer.persona_mode),
        (load_override().selected_values(document, environment)[0], pipeline.access_mode),
    )
    for values, resolve in selections:
        if flag in ("yes", ""):
            with pytest.raises(ValueError, match="enablePersonas"):
                resolve(values)
        else:
            assert resolve(values) == ("groups-v1" if flag in (True, "true") else "legacy")
    assert document == original


@pytest.mark.parametrize("environment", ["stage", "test", "prod"])
@pytest.mark.parametrize("section", ["stage_prod", "exact"])
@pytest.mark.parametrize("selected", ["legacy", "groups-v1", "invalid"])
def test_mode_alias_overlay_and_manifest_use_later_section(environment, section, selected):
    from .test_template_flag_sync import load_override
    target = ("test" if environment == "stage" else environment) if section == "exact" else section
    document = {"dev": {"persona_access_mode": "groups-v1" if selected == "legacy" else "legacy",
                        "persona_access_manifest": "access/dev.json"},
                target: {"PERSONA_ACCESS_MODE": selected,
                         "PERSONA_ACCESS_MANIFEST": "access/later.json"}}
    original = copy.deepcopy(document)
    for values in (pipeline.select_config(document, environment),
                   core.selected_config(document, environment),
                   serializer.selected_persona_values(document, environment),
                   load_override().selected_values(document, environment)[0]):
        assert values["persona_access_manifest"] == "access/later.json"
        if selected == "invalid":
            with pytest.raises(ValueError, match="persona_access_mode"):
                pipeline.access_mode(values)
        else:
            assert pipeline.access_mode(values) == selected
    assert document == original


def test_same_section_canonical_precedence_matches_all_consumers():
    from .test_template_flag_sync import load_override
    document = {"dev": {"enablePersonas": False, "ENABLEPERSONAS": True, "ENABLE_PERSONAS": "yes",
                        "persona_access_mode": "legacy", "PERSONA_ACCESS_MODE": "invalid"}}
    for values in (pipeline.select_config(document, "dev"), core.selected_config(document, "dev"),
                   load_override().selected_values(document, "dev")[0]):
        assert pipeline.access_mode(values) == "legacy"
        assert not {"ENABLEPERSONAS", "ENABLE_PERSONAS", "PERSONA_ACCESS_MODE"} & values.keys()


def test_alias_order_without_canonical_name_matches_all_consumers():
    from .test_template_flag_sync import load_override
    document = {"dev": {"ENABLEPERSONAS": False, "ENABLE_PERSONAS": True}}
    for values in (pipeline.select_config(document, "dev"), core.selected_config(document, "dev"),
                   serializer.selected_persona_values(document, "dev"),
                   load_override().selected_values(document, "dev")[0]):
        assert pipeline.access_mode(values) == "legacy"
    assert core.selected_config(document["dev"], "dev") == {"enablePersonas": False}
    assert document == {"dev": {"ENABLEPERSONAS": False, "ENABLE_PERSONAS": True}}


@pytest.mark.parametrize("alias", ["ENABLEPERSONAS", "ENABLE_PERSONAS"])
@pytest.mark.parametrize("flag", [True, False, "yes"])
def test_bridge_rereads_same_selected_mode_as_exporter(alias, flag, tmp_path, monkeypatch, capsys):
    values = {**inputs("test"), "enablePersonas": flag is not True}
    manifest_file(tmp_path, values, "test")
    document = {"dev": values, "stage_prod": {alias: flag}}
    config = tmp_path / "variables.json"
    config.write_text(json.dumps(document))
    before = config.read_bytes()
    monkeypatch.setattr(sys, "argv", ["personas", "--config", str(config), "--repo-root", str(tmp_path),
                                     "--environment", "stage", "--scope", "project", "--phase", "validate"])
    result = pipeline.main()
    output = capsys.readouterr()
    if flag == "yes":
        assert result == 1 and "enablePersonas" in output.err
    else:
        assert result == 0, output.err
        assert json.loads(output.out)["mode"] == ("groups-v1" if flag else "legacy")
    assert config.read_bytes() == before


@pytest.mark.parametrize("alias", ["ENABLEPERSONAS", "ENABLE_PERSONAS"])
def test_merge_and_downgrade_guard_respect_later_alias(tmp_path, alias):
    template, active = tmp_path / "template.json", tmp_path / "active.json"
    document = {"dev": {"enablePersonas": False}, "stage_prod": {alias: True}}
    template.write_text(json.dumps({"dev": {"enablePersonas": False}}))
    active.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Refusing"):
        serializer.guard_persona_downgrade(active, {"enablePersonas": False})
    serializer.merge_json_template(template, active)
    merged = json.loads(active.read_text())
    assert merged["dev"] == document["dev"]
    for environment in ("test", "prod"):
        assert core.mode(core.selected_config(merged, environment)) == "groups-v1"


def test_guard_and_merge_do_not_hide_invalid_later_alias_when_dev_enabled(tmp_path):
    active, template = tmp_path / "active.json", tmp_path / "template.json"
    active.write_text(json.dumps({"dev": {"enablePersonas": True},
                                  "stage_prod": {"ENABLE_PERSONAS": "yes"}}))
    template.write_text(json.dumps({"dev": {"enablePersonas": False}}))
    before = active.read_bytes()
    with pytest.raises(ValueError, match="enablePersonas"):
        serializer.guard_persona_downgrade(active, {"enablePersonas": True})
    with pytest.raises(ValueError, match="enablePersonas"):
        serializer.merge_json_template(template, active)
    assert active.read_bytes() == before
