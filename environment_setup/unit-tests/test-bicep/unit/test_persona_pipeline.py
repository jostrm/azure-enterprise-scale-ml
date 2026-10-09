"""Offline lifecycle wiring, fail-closed configuration and bootstrap contracts."""
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
sys.path.insert(0, str(BICEP))
from personas import pipeline

TEMPLATES = BICEP / "copy_to_local_settings"
SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"


def inputs(environment="dev"):
    return {
        "persona_access_mode": "groups-v1", "persona_access_manifest": "access/personas.json",
        "tenantId": TENANT, f"{environment}_sub_id": SUBSCRIPTION,
        "admin_aifactoryPrefixRG": "acme-", "admin_aifactorySuffixRG": "-001",
        "admin_locationSuffix": "weu", "project_number_000": "001",
        "technical_admins_ad_object_id": "old-admin", "technical_admins_email": "old@example.test",
    }


def manifest_file(root, values, environment="dev"):
    scopes = pipeline.deployment_scopes(values, environment)
    document = {
        "schema": "aifactory.persona-access/v1", "tenant_id": TENANT, "factory": "acme",
        "scaleset": "001", "environment": environment, "project": "project001",
        "seeding": {"subscription_id": SUBSCRIPTION, "resource_group": "seed-rg", "vault_name": "seed-vault"},
        "common_scope": scopes["common"], "project_scope": scopes["project"],
        "log_analytics_resource_id": scopes["common"] + "/providers/Microsoft.OperationalInsights/workspaces/common-log",
        "lake": {"tenant_id": TENANT, "subscription_id": SUBSCRIPTION,
                 "resource_group": scopes["common"].split("/")[-1],
                 "storage_account": "isolatedlake", "filesystem": "lake3",
                 "project": "project001", "environment": environment},
    }
    destination = root / "access/personas.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document), encoding="utf-8")
    return document


@pytest.mark.parametrize("mode", ["future", "", "Groups-V1"])
def test_unsupported_mode_fails_before_any_read_or_write(tmp_path, mode):
    cli = Mock()
    with pytest.raises(ValueError, match="Unsupported"):
        pipeline.run({**inputs(), "persona_access_mode": mode}, "dev", tmp_path, "project", "preflight", cli)
    cli.assert_not_called()


@pytest.mark.parametrize("mode", ["legacy", "groups-v1"])
@pytest.mark.parametrize("phase", ["validate", "preflight", "apply"])
def test_runtime_subscription_conflict_fails_before_legacy_return_or_cloud(tmp_path, mode, phase):
    cli = Mock()
    values = {**inputs(), "persona_access_mode": mode,
              "dev_test_prod_sub_id": "33333333-3333-4333-8333-333333333333"}
    with pytest.raises(ValueError, match="must agree"):
        pipeline.run(values, "dev", tmp_path, "project", phase, cli)
    cli.assert_not_called()
    with pytest.raises(ValueError, match="must agree"):
        pipeline.guard_downgrade(values, "dev", mode, cli)
    cli.assert_not_called()


def test_legacy_marker_checks_use_actual_runtime_subscription(tmp_path):
    runtime = "33333333-3333-4333-8333-333333333333"
    values = {**inputs(), "persona_access_mode": "legacy", "dev_sub_id": "",
              "dev_test_prod_sub_id": runtime}
    cli = Mock(return_value=False)
    pipeline.run(values, "dev", tmp_path, "common", "preflight", cli)
    assert len(cli.call_args_list) == 2
    assert all(call.args[3] == runtime for call in cli.call_args_list)


@pytest.mark.parametrize("path", ["", "../escape.json", "/absolute.json", "C:\\outside.json", "missing.json"])
def test_manifest_path_is_required_and_repository_bound(tmp_path, path):
    with pytest.raises(ValueError):
        pipeline.configuration({**inputs(), "persona_access_manifest": path}, "dev", tmp_path)


def test_stage_and_test_select_same_exact_manifest():
    document = {"dev": {"shared": 1, "persona_access_manifest": "dev.json"},
                "stage_prod": {"shared": 2}, "test": {"persona_access_manifest": "test.json"},
                "prod": {"persona_access_manifest": "prod.json"}}
    assert pipeline.select_config(document, "stage") == pipeline.select_config(document, "test")
    assert pipeline.select_config(document, "stage")["persona_access_manifest"] == "test.json"
    assert pipeline.select_config(document, "prod")["persona_access_manifest"] == "prod.json"


def test_flat_or_unknown_configuration_cannot_silently_select_legacy():
    with pytest.raises(ValueError, match="sections"):
        pipeline.select_config({"persona_access_mode": "groups-v1"}, "dev")


@pytest.mark.parametrize("flag", ["true", "false", ""])
def test_project_model_requires_explicit_manifest_coordinates_even_when_old_flag_disabled(tmp_path, flag):
    values = {**inputs(), "enableProjectLakeAccess": flag}
    document = manifest_file(tmp_path, values)
    del document["lake"]
    (tmp_path / "access/personas.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="explicit HNS lake"):
        pipeline.configuration(values, "dev", tmp_path)


def test_manifest_scopes_must_match_actual_bicep_names(tmp_path):
    values = inputs()
    document = manifest_file(tmp_path, values)
    assert pipeline.configuration(values, "dev", tmp_path)[0] == "groups-v1"
    document["project_scope"] = document["project_scope"].replace("project001", "project002")
    (tmp_path / "access/personas.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="generated deployment RG"):
        pipeline.configuration(values, "dev", tmp_path)


def test_windows_manifest_separator_supported(tmp_path):
    values = inputs()
    manifest_file(tmp_path, values)
    values["persona_access_manifest"] = "access\\personas.json"
    assert pipeline.configuration(values, "dev", tmp_path)[1]["project"] == "project001"


def test_preflight_reads_seed_only_and_clears_every_legacy_human_channel(tmp_path, monkeypatch):
    values = inputs()
    manifest_file(tmp_path, values)
    seed = Mock(return_value={"persona200": "core", "persona213": "ai"})
    provision = Mock()
    monkeypatch.setattr(pipeline.groups, "resolve_seeded_groups", seed)
    monkeypatch.setattr(pipeline.access, "provision", provision)
    cli = Mock(return_value=False)
    report = pipeline.run(values, "dev", tmp_path, "common", "preflight", cli)
    assert seed.call_args.kwargs["scope"] == "project"  # Includes initial project001 before common creation.
    assert report["status"] == "seed-validated"
    assert all(report["variables"][name] == "" for name in pipeline.HUMAN_CHANNELS)
    assert json.loads(report["variables"]["tags"])[pipeline.MARKER] == "groups-v1"
    provision.assert_not_called()
    assert all(call.args[:2] == ("group", "exists") for call in cli.call_args_list)


def test_missing_seed_has_actionable_error_and_no_fallback(tmp_path, monkeypatch):
    manifest_file(tmp_path, inputs())
    monkeypatch.setattr(pipeline.groups, "resolve_seeded_groups", Mock(side_effect=ValueError("missing record")))
    with pytest.raises(ValueError, match="bootstrapped and published"):
        pipeline.run(inputs(), "dev", tmp_path, "common", "preflight", Mock(return_value=False))


def test_existing_project_preview_blocks_before_templates_or_mutating_apply(tmp_path, monkeypatch):
    manifest_file(tmp_path, inputs())
    monkeypatch.setattr(pipeline.groups, "resolve_seeded_groups", Mock(return_value={}))
    provision = Mock(return_value={"state": "blocked", "blockers": ["legacy vault policy requires review"]})
    monkeypatch.setattr(pipeline.access, "provision", provision)
    cli = Mock(side_effect=[True, {"tags": {}}, True, {"tags": {}}])
    with pytest.raises(ValueError, match="before any template"):
        pipeline.run(inputs(), "dev", tmp_path, "project", "preflight", cli)
    assert provision.call_args.kwargs == {"scope": "project", "execute": False, "cli": cli}


def test_new_project_in_existing_common_audits_only_common(tmp_path, monkeypatch):
    manifest_file(tmp_path, inputs())
    monkeypatch.setattr(pipeline.groups, "resolve_seeded_groups", Mock(return_value={}))
    provision = Mock(return_value={"state": "preview", "blockers": []})
    monkeypatch.setattr(pipeline.access, "provision", provision)
    cli = Mock(side_effect=[True, {"tags": {}}, False])
    pipeline.run(inputs(), "dev", tmp_path, "project", "preflight", cli)
    assert provision.call_args.kwargs == {"scope": "common", "execute": False, "cli": cli}


def test_apply_calls_engine_explicitly_with_selected_scope(tmp_path, monkeypatch):
    values = inputs()
    manifest_file(tmp_path, values)
    provision = Mock(return_value={"complete": True})
    monkeypatch.setattr(pipeline.access, "provision", provision)
    cli = Mock(return_value=False)
    report = pipeline.run(values, "dev", tmp_path, "project", "apply", cli)
    assert report["status"] == "applied"
    assert provision.call_args.kwargs == {"scope": "project", "execute": True, "cli": cli}


def test_deletion_never_provisions_or_deletes_groups(tmp_path, monkeypatch):
    values = {**inputs(), "deleteAllForProject": "true"}
    manifest_file(tmp_path, values)
    provision = Mock()
    monkeypatch.setattr(pipeline.access, "provision", provision)
    assert pipeline.run(values, "dev", tmp_path, "project", "apply", Mock(return_value=False))["status"] == "deletion-preserves-groups"
    provision.assert_not_called()


def test_existing_marker_blocks_legacy_before_any_write(tmp_path):
    cli = Mock(side_effect=[True, {"tags": {pipeline.MARKER: "groups-v1"}}])
    with pytest.raises(ValueError, match="refusing downgrade"):
        pipeline.run({**inputs(), "persona_access_mode": "legacy"}, "dev", tmp_path, "project", "preflight", cli)
    assert len(cli.call_args_list) == 2


def test_legacy_keeps_original_principal_configuration(tmp_path):
    values = {**inputs(), "persona_access_mode": "legacy"}
    report = pipeline.run(values, "dev", tmp_path, "project", "preflight", Mock(return_value=False))
    assert report["variables"] == {**pipeline.mode_variables("legacy"), "persona_preflight_ready": "true"}
    assert values["technical_admins_ad_object_id"] == "old-admin"


def test_github_every_common_environment_has_ordered_mandatory_hooks():
    document = yaml.safe_load((TEMPLATES / "github-actions/infra-common.yml").read_text(encoding="utf-8"))
    for job in document["jobs"].values():
        steps = job["steps"]
        pre = next(i for i, step in enumerate(steps) if step.get("name") == "Persona access preflight (mandatory)")
        deploy = next(i for i, step in enumerate(steps) if step.get("name") == "01_az_bicep_common_rg")
        post = next(i for i, step in enumerate(steps) if step.get("name") == "Reconcile common persona access (mandatory)")
        assert pre < deploy < post
        assert "if" not in steps[pre] and "if" not in steps[post]
        assert "--environment " + job["env"]["dev_test_prod"] in steps[pre]["run"]


def test_github_project_reconciles_after_foundry_without_debug_skip():
    document = yaml.safe_load((TEMPLATES / "github-actions/infra-project-phase.yml").read_text(encoding="utf-8"))
    steps = document["jobs"]["deploy-project"]["steps"]
    pre = next(i for i, step in enumerate(steps) if step.get("name", "").startswith("Persona access preflight"))
    foundation = next(i for i, step in enumerate(steps) if step.get("name") == "61-foundation")
    post = next(i for i, step in enumerate(steps) if step.get("name", "").startswith("Reconcile common and project"))
    assert pre < foundation < post
    assert steps[post]["if"] == "inputs.phase == 'foundry'"
    assert "--scope common --phase apply" in steps[post]["run"]
    assert "--scope project --phase apply" in steps[post]["run"]
    for name in ("102-project-lake-access", "Check and Delete Current Project Orphan Role Assignments"):
        step = next(step for step in steps if step.get("name") == name)
        assert "persona_access_mode != 'groups-v1'" in step["if"]


def test_ado_lifecycle_hooks_and_non_skippable_final_reconcile():
    root = TEMPLATES / "azure-devops/esml-yaml-pipelines"
    for path in ("esml-infra-common/jobs/job-1-aif-cmn.yaml",
                 "esml-infra-project/jobs/job-1-genai-networking.yaml",
                 "esml-infra-project/jobs/job-2-genai-services.yaml"):
        text = (root / path).read_text(encoding="utf-8")
        assert text.index("persona-access-steps.yaml") < text.index("- task: AzureCLI@2")
    project = (root / "esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8")
    assert "- ${{ if eq(parameters.phase, 'foundry') }}:" in project
    assert "scope: project\n      phase: apply" in project
    assert "scope: common\n      phase: apply" in project


def test_bootstrap_does_not_reuse_one_group_across_new_personas():
    spec = importlib.util.spec_from_file_location("persona_bootstrap", ROOT / "bootstrap/lib/aifactory_scaleset_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = importlib.util.spec_from_file_location("bootstrap_fixture", Path(__file__).with_name("test_bootstrap_scaleset.py"))
    test_module = importlib.util.module_from_spec(fixture)
    fixture.loader.exec_module(test_module)
    state = {**test_module.state(), "persona_access_mode": "groups-v1", "persona_access_manifest": "access/personas.json"}
    values = module.common_values(state)
    for field in ("technical_admins_ad_object_id", "technical_admins_email",
                  "groups_coreteam_members", "groups_project_members_genai_1"):
        assert values[field] == ""
    source = (ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
    start = source.index("aif_ensure_team_group()")
    assert source.index('== groups-v1', start) < source.index('az ad group', start)
    assert source.index("aif_persona_preflight || return") < source.index("  aif_register_resource_providers", source.index("aif_scaleset_main()"))


def test_new_mode_guards_broad_workload_lake_grants_and_shared_keys():
    shared = (BICEP / "esml-genai-1/08b-rbac-common-rg.bicep").read_text(encoding="utf-8")
    for line in shared.splitlines():
        if line.startswith("module rbacLake"):
            assert "personaAccessMode == 'legacy'" in line
    lake = (BICEP / "modules/dataLake.bicep").read_text(encoding="utf-8")
    assert "allowSharedKeyAccess: !(contains(tags, 'AIF-Persona-Access')" in lake
    project_storage = (BICEP / "modules/storageAccount.bicep").read_text(encoding="utf-8")
    shared_key_lines = [line for line in project_storage.splitlines() if "allowSharedKeyAccess:" in line]
    assert len(shared_key_lines) == 2
    assert all("AIF-Persona-Access" in line and "'groups-v1'" in line for line in shared_key_lines)
    core = (BICEP / "esml-genai-1/02-core-infrastructure.bicep").read_text(encoding="utf-8")
    storage_start = core.index("storageAccountName: storageAccount1001Name")
    storage_end = core.index("containers:", storage_start)
    assert "tags: union(tagsProject, {" in core[storage_start:storage_end]
    vault = (BICEP / "modules/keyVault.bicep").read_text(encoding="utf-8")
    assert "enableRbacAuthorization: contains(tags, 'AIF-Persona-Access')" in vault
    common = (BICEP / "esml-common/main/13-rgLevel.bicep").read_text(encoding="utf-8")
    for line in common.splitlines():
        if line.startswith("module ") and "kvCmnAccessPolicys.bicep" in line:
            assert "!personaGroupsEnabled" in line


def test_bootstrap_local_downgrade_rejected_before_any_mutable_action(tmp_path):
    from .test_simple_bootstrap import bash, function, LIB
    import shlex
    path = tmp_path / "aifactory" / "variables.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"dev": {"persona_access_mode": "groups-v1",
                                       "persona_access_manifest": "access/personas.json"}}))
    result = bash(
        f"AIF_PYTHON=({shlex.quote(sys.executable)}); "
        f"AIF_SCALESET_LIB_DIR={shlex.quote(str(LIB))}; AIF_REPO_ROOT={shlex.quote(str(tmp_path))}; "
        "AIF_PERSONA_ACCESS_MODE=legacy; AIF_PERSONA_ACCESS_MANIFEST=''; "
        "aif_load_persona_configuration; echo UNEXPECTED_MUTATION",
        "aif_load_persona_configuration",
    )
    assert result.returncode != 0 and "Refusing to replace groups-v1" in result.stderr
    assert "UNEXPECTED" not in result.stdout + result.stderr
    main = function("aif_scaleset_main")
    gate = main.index("aif_load_persona_configuration || return")
    assert gate < main.index('mkdir -p "$state_parent"')
    assert gate < main.index("aif_ensure_target_repository") < main.index("aif_register_resource_providers")
    assert json.loads(path.read_text())["dev"]["persona_access_mode"] == "groups-v1"


@pytest.mark.parametrize("manifest_path", ["access/personas.json", "access\\personas.json"])
def test_simple_bootstrap_accepts_only_pre_staged_manifest_real_paths(tmp_path, manifest_path):
    from .test_simple_bootstrap import bash, LIB
    import shlex
    manifest_file(tmp_path, inputs())
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = bash(
        f"AIF_PYTHON=({shlex.quote(sys.executable)}); "
        f"AIF_SCALESET_LIB_DIR={shlex.quote(str(LIB))}; AIF_REPO_ROOT={shlex.quote(str(tmp_path))}; "
        f"AIF_PERSONA_ACCESS_MODE=groups-v1; AIF_PERSONA_ACCESS_MANIFEST={shlex.quote(manifest_path)}; "
        "AIF_SIMPLE_MODE=true; aif_validate_simple_target",
        "aif_validate_simple_target",
    )
    assert result.returncode == 0, result.stderr
    assert before == {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


@pytest.mark.parametrize("extra", ["README.txt", ".git/config", "access/other.json", "empty-directory"])
def test_simple_manifest_exception_does_not_allow_other_existing_content(tmp_path, extra):
    from .test_simple_bootstrap import CONFIG
    manifest_file(tmp_path, inputs())
    path = tmp_path / extra
    if extra == "empty-directory":
        path.mkdir()
    else:
        path.parent.mkdir(exist_ok=True)
        path.write_text("preserve me")
    with pytest.raises(ValueError, match="only the reviewed persona manifest"):
        CONFIG.validate_simple_target(tmp_path, "groups-v1", "access/personas.json")
    assert path.exists()


def test_simple_manifest_exception_rejects_hardlinks_and_missing_manifests(tmp_path):
    from .test_simple_bootstrap import CONFIG
    with pytest.raises(ValueError, match="Stage the reviewed"):
        CONFIG.validate_simple_target(tmp_path, "groups-v1", "access/personas.json")
    manifest_file(tmp_path, inputs())
    (tmp_path / "linked.json").hardlink_to(tmp_path / "access" / "personas.json")
    with pytest.raises(ValueError, match="only the reviewed"):
        CONFIG.validate_simple_target(tmp_path, "groups-v1", "access/personas.json")


def test_simple_legacy_still_requires_empty_target(tmp_path):
    from .test_simple_bootstrap import CONFIG
    CONFIG.validate_simple_target(tmp_path)
    manifest_file(tmp_path, inputs())
    with pytest.raises(ValueError, match="new empty target"):
        CONFIG.validate_simple_target(tmp_path)
