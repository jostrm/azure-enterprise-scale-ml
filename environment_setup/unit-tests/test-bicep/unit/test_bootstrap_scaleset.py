"""Offline tests for the end-to-end AI Factory scale-set bootstrap."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
BOOTSTRAP = ROOT / "bootstrap"
CONFIG_HELPER = BOOTSTRAP / "lib/aifactory_scaleset_config.py"
ADO_VARIABLES = (
    ROOT
    / "environment_setup/aifactory/bicep/copy_to_local_settings"
    / "azure-devops/esml-yaml-pipelines/variables/variables.yaml"
)
GHA_ROOT = (
    ROOT
    / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions"
)
VARIABLES_JSON = ROOT / "environment_setup/aifactory/variables.json"

SPEC = importlib.util.spec_from_file_location("aifactory_scaleset_config", CONFIG_HELPER)
assert SPEC and SPEC.loader
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


def state() -> dict[str, object]:
    return {
        "topology": "s",
        "network_mode": "priv",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "dev_subscription_id": "22222222-2222-2222-2222-222222222222",
        "stage_subscription_id": "22222222-2222-2222-2222-222222222222",
        "prod_subscription_id": "22222222-2222-2222-2222-222222222222",
        "location": "swedencentral",
        "location_short": "sdc",
        "dev_vnet_cidr": "172.16.0.0/18",
        "prefix": "acme-",
        "scaleset_suffix": "-001",
        "project_number": "001",
        "team_group_id": "33333333-3333-3333-3333-333333333333",
        "team_group_name": "acme-prj001-team",
        "ip_allowlist": "",
        "seeding_subscription_id": "22222222-2222-2222-2222-222222222222",
        "seeding_resource_group": "rg-acme-bootstrap-sdc-001",
        "seeding_keyvault_name": "kvacmesdc001",
        "enable_public_genai_access": "false",
        "allow_public_access_behind_vnet": "false",
        "enable_public_perimeter": "false",
        "add_bastion": "true",
        "hub_subscription_id": "",
        "hub_resource_group": "",
        "project_sp_secret_names": {"app_id": "", "object_id": "", "secret": ""},
        "azure_ml_principal_id": "44444444-4444-4444-4444-444444444444",
        "ado_tenant_id": "11111111-1111-1111-1111-111111111111",
        "dev_service_connection": "sc-acme-dev-001",
        "stage_service_connection": "sc-acme-dev-001",
        "prod_service_connection": "sc-acme-dev-001",
        "github_repository": "contoso/acme-aifactory-001",
        "oidc_client_id": "55555555-5555-5555-5555-555555555555",
    }


class TestScaleSetConfiguration(unittest.TestCase):
    def test_subnet_plan_uses_first_four_26_networks(self) -> None:
        plan = CONFIG.subnet_plan("172.16.0.0/18")
        self.assertEqual(plan["common_subnet_cidr"], "172.16.0.0/26")
        self.assertEqual(plan["common_subnet_scoring_cidr"], "172.16.0.64/26")
        self.assertEqual(plan["common_pbi_subnet_cidr"], "172.16.0.128/26")
        self.assertEqual(plan["common_bastion_subnet_cidr"], "172.16.0.192/26")
        with self.assertRaises(ValueError):
            CONFIG.subnet_plan("172.16.0.0/19")

    def test_ado_configuration_has_no_service_principal_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            yaml_target = (
                repo
                / "aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"
            )
            yaml_target.parent.mkdir(parents=True)
            shutil.copy2(ADO_VARIABLES, yaml_target)
            json_target = repo / "aifactory/variables.json"
            shutil.copy2(VARIABLES_JSON, json_target)

            CONFIG.apply_ado(repo, state())

            yaml = yaml_target.read_text(encoding="utf-8")
            self.assertIn('dev_service_connection: "sc-acme-dev-001"', yaml)
            self.assertIn('common_vnet_cidr: "172.16.0.0/18"', yaml)
            self.assertIn(
                'project_service_principal_OID_seeding_kv_name: ""',
                yaml,
            )
            self.assertIn(
                'technical_admins_ad_object_id: "33333333-3333-3333-3333-333333333333"',
                yaml,
            )
            self.assertIn('enableAdminVM: "true"', yaml)

    def test_template_merges_preserve_values_and_add_new_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active_yaml = root / "variables.yaml"
            template_yaml = root / "variables-template.yaml"
            active_yaml.write_text('variables:\n  existing: "custom"\n', encoding="utf-8")
            template_yaml.write_text(
                'variables:\n  existing: "default"\n  added: "new-default"\n',
                encoding="utf-8",
            )
            CONFIG.merge_yaml_template(template_yaml, active_yaml)
            merged_yaml = active_yaml.read_text(encoding="utf-8")
            self.assertIn('existing: "custom"', merged_yaml)
            self.assertIn('added: "new-default"', merged_yaml)

            active_env = root / ".env"
            template_env = root / ".env.template"
            active_env.write_text('EXISTING="custom"\n', encoding="utf-8")
            template_env.write_text(
                'EXISTING="default"\nADDED="new-default"\n',
                encoding="utf-8",
            )
            CONFIG.merge_env_template(template_env, active_env)
            merged_env = active_env.read_text(encoding="utf-8")
            self.assertIn('EXISTING="custom"', merged_env)
            self.assertIn('ADDED="new-default"', merged_env)

    def test_github_configuration_selects_oidc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            env_target = repo / ".env"
            shutil.copy2(GHA_ROOT / ".env.template", env_target)
            json_target = repo / "aifactory/variables.json"
            json_target.parent.mkdir(parents=True)
            shutil.copy2(VARIABLES_JSON, json_target)

            CONFIG.apply_gha(repo, state())

            env = env_target.read_text(encoding="utf-8")
            self.assertIn(
                'AZURE_CLIENT_ID="55555555-5555-5555-5555-555555555555"',
                env,
            )
            self.assertIn(
                'TENANT_AZUREML_OID="44444444-4444-4444-4444-444444444444"',
                env,
            )
            self.assertIn(
                'ALLOW_PUBLIC_ACCESS_WHEN_BEHIND_VNET="false"',
                env,
            )
            payload = json.loads(json_target.read_text(encoding="utf-8"))
            self.assertEqual(payload["dev"]["project_number_000"], "001")
            self.assertEqual(
                payload["dev"]["project_service_principal_OID_seeding_kv_name"],
                "",
            )


class TestScaleSetWorkflowContracts(unittest.TestCase):
    def test_github_workflows_support_oidc_and_sp_fallback(self) -> None:
        common = (GHA_ROOT / "infra-common.yml").read_text(encoding="utf-8")
        project = (GHA_ROOT / "infra-project.yml").read_text(encoding="utf-8")
        phase = (GHA_ROOT / "infra-project-phase.yml").read_text(encoding="utf-8")
        publisher = (
            GHA_ROOT / "03a-GH-create-or-update-github-variables.sh"
        ).read_text(encoding="utf-8")

        self.assertEqual(common.count("client-id: ${{ env.AZURE_CLIENT_ID }}"), 3)
        self.assertEqual(common.count("creds: ${{ secrets.AZURE_CREDENTIALS }}"), 3)
        self.assertRegex(common, r"(?m)^\s*id-token: write\s*$")
        self.assertRegex(project, r"(?m)^\s*id-token: write\s*$")
        self.assertIn("client-id: ${{ env.AZURE_CLIENT_ID }}", phase)
        self.assertIn("creds: ${{ secrets.AZURE_CREDENTIALS }}", phase)
        self.assertRegex(phase, r"(?m)^\s*id-token: write\s*$")
        for variable in (
            "ADD_BASTION_HOST",
            "ENABLE_ADMIN_VM",
            "CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB",
            "ENABLE_PUBLIC_ACCESS_WITH_PERIMETER",
        ):
            self.assertIn(f'"{variable}"', publisher)

    def test_entrypoints_and_start_script_are_wired(self) -> None:
        shared = (BOOTSTRAP / "lib/create-new-aifactory-scaleset.sh").read_text(
            encoding="utf-8"
        )
        start = (ROOT / "00-start.sh").read_text(encoding="utf-8")
        for entrypoint in (
            "ADO-create-new-aifactory-scaleset.sh",
            "GHA-create-new-aifactory-scaleset.sh",
        ):
            self.assertTrue((BOOTSTRAP / entrypoint).is_file())
            self.assertIn(entrypoint, start)
        for required_flow in (
            "aif_register_resource_providers",
            "aif_ensure_seeding_keyvault",
            "aif_ensure_team_group",
            "aif_verify_common_resource_group",
        ):
            self.assertIn(required_flow, shared)
        self.assertNotIn("Cross-tenant Azure DevOps requires PAT", shared)
        self.assertIn(
            "Azure Machine Learning enterprise application is not materialized",
            shared,
        )


if __name__ == "__main__":
    unittest.main()
