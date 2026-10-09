"""Key-only consumer inventory and runtime wiring regressions; no customer values."""
import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
INFRA = ROOT / "environment_setup/aifactory"
TEMPLATES = INFRA / "bicep/copy_to_local_settings"
ADO = TEMPLATES / "azure-devops/esml-yaml-pipelines"
GHA = TEMPLATES / "github-actions"
ALIASES = {"acrIpWhitelist": "acr_IP_whitelist", "admin_username": "adminUsername"}
DEFAULTS = {
    "enablePersonas": False,
    "aksSkuTier": "Standard",
    "enableProjectVM": False,
    "updateRbac": False,
    **{key: True for key in (
        "skipDiagAISearch", "skipDiagAIServices", "skipDiagAOAI",
        "skipDiagContentSafety", "skipDiagDocIntelligence", "skipDiagSpeech", "skipDiagVision",
    )},
}
ENV_NAMES = {
    "enablePersonas": "ENABLE_PERSONAS", "aksSkuTier": "AKS_SKU_TIER",
    "enableProjectVM": "ENABLE_PROJECT_VM", "updateRbac": "UPDATE_RBAC",
    "skipDiagAISearch": "SKIP_DIAG_AI_SEARCH", "skipDiagAIServices": "SKIP_DIAG_AI_SERVICES",
    "skipDiagAOAI": "SKIP_DIAG_AOAI", "skipDiagContentSafety": "SKIP_DIAG_CONTENT_SAFETY",
    "skipDiagDocIntelligence": "SKIP_DIAG_DOC_INTELLIGENCE",
    "skipDiagSpeech": "SKIP_DIAG_SPEECH", "skipDiagVision": "SKIP_DIAG_VISION",
}


def load_override():
    spec = importlib.util.spec_from_file_location(
        "template_overrides", INFRA / "bicep/scripts/apply-json-config-overrides.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_consumer_keysets_have_canonical_json_and_ado_coverage():
    inventory = json.loads((Path(__file__).parent / "fixtures/template-source-keysets.json").read_text())
    baseline = json.loads((INFRA / "variables.json").read_text())["dev"]
    ado = yaml.safe_load((ADO / "variables/variables.yaml").read_text())["variables"]
    assert set(inventory) == {"project001", "project003"}
    for sections in inventory.values():
        assert set(sections) == {"dev", "stage_prod"}
        for keys in sections.values():
            assert isinstance(keys, list) and all(isinstance(key, str) for key in keys)
            canonical = {ALIASES.get(key, key) for key in keys}
            assert canonical <= baseline.keys()
            # GitHub repository setup/OIDC selectors are not Azure DevOps inputs.
            assert canonical - {key for key in canonical if key.startswith("GITHUB_")} - {"AZURE_CLIENT_ID"} <= ado.keys()


@pytest.mark.parametrize("key,default", DEFAULTS.items())
def test_defaults_match_all_three_templates_and_upload_allowlist(key, default):
    baseline = json.loads((INFRA / "variables.json").read_text())["dev"]
    ado = yaml.safe_load((ADO / "variables/variables.yaml").read_text())["variables"]
    env = dict(re.findall(r"^([A-Z][A-Z0-9_]*)=([^#\r\n]*)", (GHA / ".env.template").read_text(), re.M))
    expected = str(default).lower() if isinstance(default, bool) else default
    for actual in (baseline[key], ado[key], env[ENV_NAMES[key]].strip().strip("'\"")):
        assert str(actual).lower() == expected.lower()
    assert f'"{ENV_NAMES[key]}"' in (GHA / "03a-GH-create-or-update-github-variables.sh").read_text()


@pytest.mark.parametrize("key", [key for key in DEFAULTS if key.startswith("skipDiag")])
def test_diagnostic_flags_reach_bicep_in_both_providers(key):
    ado = (ADO / "esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8")
    gha = (GHA / "infra-project-phase.yml").read_text(encoding="utf-8")
    assert f'--parameters {key}="$({key})"' in ado
    assert f'--parameters {key}="${{{{ env.{key} }}}}"' in gha
    assert f"{key}: ${{{{ vars.{ENV_NAMES[key]}" in gha
    if key == "skipDiagAISearch":
        spec = importlib.util.spec_from_file_location(
            "_sync_capacity_runner", INFRA / "bicep/scripts/deploy-capacity-resource.py")
        capacity = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = capacity
        try:
            spec.loader.exec_module(capacity)
            result = capacity.deployment_parameters(
                {"parameters": {key: {"type": "bool", "defaultValue": True}}},
                {"parameters": {}}, {key.upper(): "false"}, {})
            assert result["parameters"][key]["value"] is False
        finally:
            sys.modules.pop(spec.name, None)


@pytest.mark.parametrize("alias,canonical", ALIASES.items())
def test_alias_normalized_per_environment_before_overlay(alias, canonical):
    override = load_override()
    values, _ = override.selected_values({"dev": {canonical: "base"}, "stage_prod": {alias: "override"}}, "prod")
    assert values[canonical] == "override"
    assert alias not in values
    values, _ = override.selected_values({"dev": {alias: "old", canonical: "current"}}, "dev")
    assert values[canonical] == "current"


def test_quoted_github_workflow_mapping_is_consumed():
    mappings = load_override().github_runtime_names(str(GHA / "infra-common.yml"))
    assert "adminUsername" in mappings["ADMIN_USERNAME"]


@pytest.mark.parametrize("alias", ["ENABLE_PERSONAS", "ENABLEPERSONAS"])
def test_persona_alias_overlay_is_authoritative(alias):
    values, _ = load_override().selected_values(
        {"dev": {"enablePersonas": False}, "stage_prod": {alias: True}}, "prod")
    assert values["enablePersonas"] == "true"


@pytest.mark.parametrize("template", ["05-compute-services", "07-ml-data-platform", "10-aifactory-dashboards"])
def test_aks_tier_reaches_each_aks_consumer(template):
    for path, expected in [
        (ADO / "esml-infra-project/jobs/job-2-genai-services.yaml", '--parameters aksSkuTier="$(aksSkuTier)"'),
        (GHA / "infra-project-phase.yml", '--parameters aksSkuTier="${{ env.aksSkuTier }}"'),
    ]:
        text = path.read_text(encoding="utf-8")
        command = text.split(f"/{template}.bicep", 1)[1].split("\n\n", 1)[0]
        assert expected in command


def test_github_project_type_is_not_cosmetic():
    assert 'ADMIN_PROJECT_TYPE="all"' in (GHA / ".env.template").read_text()
    assert '"ADMIN_PROJECT_TYPE"' in (GHA / "03a-GH-create-or-update-github-variables.sh").read_text()
    assert "admin_projectType: ${{ vars.ADMIN_PROJECT_TYPE || 'all' }}" in (GHA / "infra-project-phase.yml").read_text(encoding="utf-8")


def test_github_source_coverage_accounts_for_provider_aliases_and_exclusions():
    inventory = json.loads((Path(__file__).parent / "fixtures/template-source-keysets.json").read_text())
    env = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", (GHA / ".env.template").read_text(), re.M))
    normalize = lambda name: re.sub("[^a-z0-9]", "", name.lower())
    normalized = {normalize(key) for key in env}
    mappings = {}
    for workflow in GHA.glob("*.yml"):
        for source, targets in load_override().github_runtime_names(str(workflow)).items():
            if source in env:
                for target in targets:
                    mappings[target] = source
    mappings.update({
        "aifactory-dash-01": "AIFACTORY_DASHBOARD_URL",
        "commonLakeNamePrefixMax8chars": "LAKE_PREFIX",
        "debug_disable_67_data_ml_platform": "DEBUG_DISABLE_67_ML_PLATFORM",
        "network_env_dev": "DEV_NETWORK_ENV", "network_env_stage": "STAGE_NETWORK_ENV",
        "network_env_prod": "PROD_NETWORK_ENV", "test_cidr_range": "STAGE_CIDR_RANGE",
        "dev_sub_id": "DEV_SUBSCRIPTION_ID", "test_sub_id": "STAGE_SUBSCRIPTION_ID",
        "prod_sub_id": "PROD_SUBSCRIPTION_ID", "project_IP_whitelist": "PROJECT_MEMBERS_IP_ADDRESS",
    })
    for prefix in ("dev", "test", "prod"):
        mappings.update({
            prefix + "_admin_bicep_input_keyvault_subscription": "AIFACTORY_SEEDING_KEYVAULT_SUBSCRIPTION_ID",
            prefix + "_admin_bicep_kv_fw": "AIFACTORY_SEEDING_KEYVAULT_NAME",
            prefix + "_admin_bicep_kv_fw_rg": "AIFACTORY_SEEDING_KEYVAULT_RG",
        })
    excluded = {
        "adminVMBuildAgentName", "adminVMBuildAgentPool", "azureDevOpsTenantId",
        "technical_admins_ad_object_id",
        *(prefix + suffix for prefix in ("dev", "test", "prod")
          for suffix in ("_service_connection", "_seeding_kv_service_connection")),
    }
    # ADO pool/connection identity has no GHA equivalent; human OIDs stay operator-owned,
    # rather than being published as guessed repository variables.
    for sections in inventory.values():
        for keys in sections.values():
            for key in keys:
                canonical = ALIASES.get(key, key)
                assert (normalize(canonical) in normalized or mappings.get(canonical) in env
                        or canonical in excluded), key


@pytest.mark.parametrize("alias,canonical", ALIASES.items())
def test_json_merge_preserves_existing_alias_values(tmp_path, alias, canonical):
    from .test_registered_personas import serializer
    template, active = tmp_path / "template.json", tmp_path / "active.json"
    template.write_text(json.dumps({"dev": {canonical: "default"}}))
    active.write_text(json.dumps({"dev": {alias: "configured"}, "stage_prod": {alias: "production"}}))
    serializer.merge_json_template(template, active)
    result = json.loads(active.read_text())
    assert result["dev"][canonical] == "configured"
    assert result["stage_prod"][canonical] == "production"
    assert result["dev"][alias] == "configured"


@pytest.mark.parametrize("provider,kind", [("GH", "json"), ("ADO", "json"), ("GH", "env"), ("ADO", "yaml")])
def test_actual_launcher_merge_keeps_mode_only_opt_in(tmp_path, monkeypatch, provider, kind):
    launcher = ROOT / "bootstrap" / f"{provider}-update-aifactory-and-run-project.sh"
    markers = {
        ("GH", "json"): '"${PYTHON[@]}" - "$CONFIG_FILE" "$CONFIG_TEMPLATE_FILE" "$RUNNER_LABEL" "$state_dir/current.env" <<\'PY\'\n',
        ("ADO", "json"): '"${PYTHON[@]}" - "$CONFIG_TEMPLATE_FILE" "$state_dir/variables.json" "$CONFIG_FILE" <<\'PY\'\n',
        ("GH", "env"): '"${PYTHON[@]}" - ".env" ".env.template" "$RUNNER_LABEL" <<\'PY\'\n',
        ("ADO", "yaml"): '"${PYTHON[@]}" - "$VARIABLES_TEMPLATE_FILE" "$state_dir/variables.yaml" "$VARIABLES_FILE" <<\'PY\'\n',
    }
    code = launcher.read_text(encoding="utf-8").split(markers[provider, kind], 1)[1].split("\nPY", 1)[0]
    active, template, output = (tmp_path / name for name in ("active", "template", "output"))
    if kind == "json":
        active.write_text(json.dumps({"dev": {"persona_access_mode": "groups-v1", "acrIpWhitelist": "configured"},
                                      "stage_prod": {"persona_access_mode": "legacy"}}))
        template.write_text(json.dumps({"dev": {"enablePersonas": False, "acr_IP_whitelist": ""}}))
        argv = ([str(active), str(template), "runner", str(tmp_path / "absent.env")] if provider == "GH"
                else [str(template), str(active), str(output)])
    elif kind == "env":
        active.write_text("PERSONA_ACCESS_MODE=groups-v1\n")
        template.write_text("ENABLE_PERSONAS=false\nPERSONA_ACCESS_MODE=legacy\n")
        argv = [str(active), str(template), "runner"]
    else:
        active.write_text('variables:\n  persona_access_mode: "groups-v1"\n')
        template.write_text('variables:\n  enablePersonas: false\n  persona_access_mode: legacy\n')
        argv = [str(template), str(active), str(output)]
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(sys, "argv", ["merge", *argv])
    exec(compile(code, str(launcher), "exec"), {"__name__": "__main__"})
    if kind == "json":
        result = json.loads((active if provider == "GH" else output).read_text())
        from .test_registered_personas import core
        assert core.mode(core.selected_config(result, "dev")) == "groups-v1"
        assert core.mode(core.selected_config(result, "prod")) == "legacy"
        assert result["dev"]["acr_IP_whitelist"] == "configured"
    elif kind == "env":
        assert "ENABLE_PERSONAS=true" in template.read_text()
    else:
        assert yaml.safe_load(output.read_text())["variables"]["enablePersonas"] is True
