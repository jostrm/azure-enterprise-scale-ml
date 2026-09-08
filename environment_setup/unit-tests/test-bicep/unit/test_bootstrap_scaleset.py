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
DNS_HELPER = BOOTSTRAP / "lib/aifactory_private_dns.py"
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
PRIVATE_DNS_POLICY_SET = (
    ROOT
    / "environment_setup/aifactory/bicep/esml-util/policyset"
    / "Deploy-Private-DNS-Zones.json"
)
PRIVATE_DNS_INITIATIVE = (
    ROOT / "environment_setup/aifactory/bicep/esml-util/28-Initiatives.bicep"
)
FOUNDRY_PRIVATE_DNS = (
    ROOT
    / "environment_setup/aifactory/bicep/modules/csFoundry/foundry-apim"
    / "modules-network-secured/private-endpoint-and-dns.bicep"
)

SPEC = importlib.util.spec_from_file_location("aifactory_scaleset_config", CONFIG_HELPER)
assert SPEC and SPEC.loader
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)
DNS_SPEC = importlib.util.spec_from_file_location("aifactory_private_dns", DNS_HELPER)
assert DNS_SPEC and DNS_SPEC.loader
DNS = importlib.util.module_from_spec(DNS_SPEC)
DNS_SPEC.loader.exec_module(DNS)


def state() -> dict[str, object]:
    return {
        "topology": "s",
        "access_hub_mode": "external",
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
        "databricks_principal_id": "66666666-6666-6666-6666-666666666666",
        "ado_tenant_id": "11111111-1111-1111-1111-111111111111",
        "dev_service_connection": "sc-acme-dev-001",
        "stage_service_connection": "sc-acme-dev-001",
        "prod_service_connection": "sc-acme-dev-001",
        "github_repository": "contoso/acme-aifactory-001",
        "oidc_client_id": "55555555-5555-5555-5555-555555555555",
        "runner_mode": "self-hosted",
        "ado_agent_pool": "Default",
        "ado_agent_name": "dsvm-cmn-sdc-dev-001",
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

    def test_private_dns_configuration_is_central_and_regional(self) -> None:
        config = DNS.configuration(
            "77777777-7777-7777-7777-777777777777",
            "aifactory-connectivity",
            "swedencentral",
            "sdc",
        )
        parameters = config["assignmentParameters"]
        zones = {item["name"] for item in config["zones"]}
        self.assertEqual(
            parameters["azureCognitiveServicesPrivateDnsZoneId"]["value"],
            "/subscriptions/77777777-7777-7777-7777-777777777777"
            "/resourceGroups/aifactory-connectivity/providers/"
            "Microsoft.Network/privateDnsZones/"
            "privatelink.cognitiveservices.azure.com",
        )
        self.assertIn("privatelink.sdc.backup.windowsazure.com", zones)
        self.assertIn("privatelink.services.ai.azure.com", zones)
        self.assertNotIn(
            "swedencentral.data.privatelink.azurecr.io",
            zones,
        )
        self.assertEqual(
            parameters["azureIotDeviceupdatePrivateDnsZoneId"]["value"].rsplit(
                "/",
                maxsplit=1,
            )[-1],
            "privatelink.api.adu.microsoft.com",
        )
        policy_set = json.loads(PRIVATE_DNS_POLICY_SET.read_text(encoding="utf-8"))
        expected_parameters = {
            name
            for name in policy_set["properties"]["parameters"]
            if "privatednszoneid" in name.lower()
        }
        self.assertEqual(set(parameters), expected_parameters)

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
            self.assertIn('useSelfHostedBuildAgent: "true"', yaml)
            self.assertIn('adminVMBuildAgentPool: "Default"', yaml)
            self.assertIn(
                'adminVMBuildAgentName: "dsvm-cmn-sdc-dev-001"',
                yaml,
            )
            self.assertIn(
                'disable_whitelisting_for_build_agents: "true"',
                yaml,
            )
            self.assertIn('centralDnsZoneByPolicyInHub: "true"', yaml)
            self.assertIn(
                'databricksOID: "66666666-6666-6666-6666-666666666666"',
                yaml,
            )

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
                'DATABRICKS_OID="66666666-6666-6666-6666-666666666666"',
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
    def test_vpn_public_ip_recovers_from_required_subscription_feature(self) -> None:
        script = (
            BOOTSTRAP / "lib/create-new-aifactory-scaleset.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Microsoft.Network/AllowBringYourOwnPublicIpAddress",
            script,
        )
        self.assertIn(
            "--name AllowBringYourOwnPublicIpAddress",
            script,
        )
        self.assertIn(
            'aif_create_vpn_public_ip \\\n'
            '      "$hub_subscription" \\\n'
            '      "$hub_resource_group" \\\n'
            '      "$public_ip_name"',
            script,
        )

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
            "aif_ensure_first_party_enterprise_apps",
            "aif_ensure_ado_self_hosted_agent",
            "aif_ensure_private_dns_policy_assignment",
            "aif_ensure_vpn_access_hub",
        ):
            self.assertIn(required_flow, shared)
        self.assertNotIn("Cross-tenant Azure DevOps requires PAT", shared)
        self.assertIn(
            "temporary Azure ML and Databricks workspaces",
            shared,
        )
        self.assertIn('"protectedParameters"', shared)
        self.assertIn(
            "Project build agent: self-hosted admin VM (s) or Microsoft-hosted (h)",
            shared,
        )
        self.assertIn("aif_ensure_dns_private_resolver", shared)

    def test_central_dns_policy_and_foundry_contracts(self) -> None:
        initiative = PRIVATE_DNS_INITIATIVE.read_text(encoding="utf-8")
        foundry_dns = FOUNDRY_PRIVATE_DNS.read_text(encoding="utf-8")
        self.assertIn("param scope string = subscription().id", initiative)
        self.assertIn("param includeCostOptimization bool = false", initiative)
        self.assertIn(
            "replace(replace(content, templateVars.scope, scope), "
            "templateVars.defaultDeploymentLocation, deploymentLocation)",
            initiative,
        )
        self.assertIn(
            "resource privateEndpointDnsGroupAIF "
            "'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {",
            foundry_dns,
        )


if __name__ == "__main__":
    unittest.main()
