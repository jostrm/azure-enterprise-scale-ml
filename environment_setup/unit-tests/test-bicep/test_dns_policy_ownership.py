"""Offline guards against project pipelines taking ownership of central private DNS."""
from __future__ import annotations

import itertools
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "environment_setup/aifactory/bicep"
ADO_DIR = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs"
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
KV_HELPER = BICEP / "scripts/prepareSeedingKeyVaultPrivateDns.ps1"
FOUNDRY_PE = BICEP / "modules/csFoundry/aiFoundry2025pend.bicep"
APIM_PE = BICEP / "modules/csFoundry/foundry-apim/modules-network-secured/private-endpoint-and-dns.bicep"


def task(path: Path, name: str) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = document.get("steps") or document["jobs"]["deploy-project"]["steps"]
    return next(s for s in steps if s.get("displayName", s.get("name")) == name)


def substitute(script: str, values: dict[str, str]) -> str:
    return re.sub(
        r"\$\((\w+)\)|\$\{\{\s*env\.(\w+)\s*\}\}",
        lambda m: values.get(m[1] or m[2], "unused"),
        script,
    )


class PipelineDnsOwnershipTests(unittest.TestCase):
    def run_shell(self, shell, script, env=None):
        command = shutil.which(shell)
        if not command:
            self.skipTest(f"{shell} is required")
        args = (
            ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script]
            if shell == "pwsh" else ["--noprofile", "--norc", "-s"]
        )
        result = subprocess.run(
            [command, *args],
            input=script.encode("utf-8") if shell != "pwsh" else None,
            env=os.environ | (env or {}),
            capture_output=True, check=False, timeout=30,
        )
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")

    def test_ado_dns_inspection_never_selects_or_queries_hub_subscription(self):
        step = task(ADO_DIR / "job-2-genai-services.yaml", "05a_Check if Private DNS Zones exist")
        for central in ("true", "True", "false"):
            with self.subTest(central=central):
                script = substitute(step["inputs"]["inlineScript"], {"centralDnsZoneByPolicyInHub": central})
                code, stdout, stderr = self.run_shell(
                    "pwsh",
                    "function az { Write-Host ('AZ_CALLED:' + ($args -join ' ')); throw 'API boundary reached' }\n" + script,
                )
                if central.lower() == "true":
                    self.assertEqual(0, code, stdout + stderr)
                    self.assertNotIn("AZ_CALLED:", stdout)
                    self.assertIn("policy-managed", stdout)
                    for key in ("zoneazurecontainerapps", "zoneredis", "zonepostgres", "zonesql", "zoneMongo", "zoneServicesAi", "zoneAPIM"):
                        self.assertIn(f"variable={key}Exists]false", stdout)
                else:
                    self.assertNotEqual(0, code)
                    self.assertIn("AZ_CALLED:account set", stdout)

    def test_search_repair_is_off_for_policy_dns_on_both_routes(self):
        steps = (
            task(ADO_DIR / "job-2-genai-services.yaml", "69-pre-account-ensure-AISearch-private-DNS-reachable"),
            task(GHA, "69-pre-account-ensure-AISearch-private-DNS-reachable"),
        )
        for step, central, byo in itertools.product(steps, ("true", "True", "false"), ("true", "false")):
            with self.subTest(route="ADO" if "inputs" in step else "GitHub", central=central, byo=byo):
                source = step["inputs"]["inlineScript"] if "inputs" in step else step["run"]
                script = substitute(source, {"centralDnsZoneByPolicyInHub": central})
                setup = (
                    f"export DNS_MANAGED_BY_POLICY={shlex.quote(central)}\n"
                    f"export BYO_subnets={byo}\n"
                    "az() { echo AZ_CALLED; exit 37; }\n"
                )
                code, stdout, stderr = self.run_shell("bash", setup + script)
                if central.lower() == "true":
                    self.assertEqual(0, code, stdout + stderr)
                    self.assertNotIn("AZ_CALLED", stdout)
                    self.assertIn("policy-managed", stdout)
                else:
                    self.assertEqual(37, code, stdout + stderr)
                    self.assertIn("AZ_CALLED", stdout)
                self.assertIn("DNS_MANAGED_BY_POLICY", step["env"])

    def test_github_zone_inspection_policy_guard_avoids_az(self):
        step = task(GHA, "15_Check_Private_DNS_Zones")
        setup = """
export DNS_MANAGED_BY_POLICY=true
GITHUB_ENV="$(mktemp)"
trap 'rm -f "$GITHUB_ENV"' EXIT
az() { echo AZ_CALLED; exit 37; }
"""
        code, stdout, stderr = self.run_shell("bash", setup + substitute(step["run"], {}))
        self.assertEqual(0, code, stdout + stderr)
        self.assertNotIn("AZ_CALLED", stdout)
        self.assertIn("policy-managed", stdout)

    def test_all_seeding_routes_pass_policy_ownership_to_shared_helper(self):
        cases = (
            (ADO_DIR / "job-1-genai-networking.yaml", "02b_az_prepare_seeding_keyvault_private_dns"),
            (ADO_DIR / "job-2-genai-services.yaml", "02b_az_prepare_seeding_keyvault_private_dns"),
            (GHA, "02b_Prepare_Seeding_KeyVault_Private_DNS"),
        )
        for path, name in cases:
            with self.subTest(path=path.name):
                step = task(path, name)
                source = step["inputs"]["inlineScript"] if "inputs" in step else step["run"]
                self.assertIn("prepareSeedingKeyVaultPrivateDns.ps1", source)
                self.assertIn("-DnsManagedByPolicy", source)
                self.assertIn("centralDnsZoneByPolicyInHub", step["env"]["DNS_MANAGED_BY_POLICY"])

    def test_services_seeding_policy_branch_does_not_enter_legacy_inline_repair(self):
        step = task(ADO_DIR / "job-2-genai-services.yaml", "02b_az_prepare_seeding_keyvault_private_dns")
        script = substitute(step["inputs"]["inlineScript"], {})
        # Intercept only the script path, not its flag/early-return logic.
        script = script.replace(
            '"$env:SYSTEM_DEFAULTWORKINGDIRECTORY/azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/prepareSeedingKeyVaultPrivateDns.ps1"',
            "Invoke-TestHelper",
        )
        fake = """
function Invoke-TestHelper {
  Write-Host ('HELPER_ARGS:' + ($args -join ' '))
}
function az { throw 'Unexpected Azure call in the legacy repair branch' }
"""
        code, stdout, stderr = self.run_shell("pwsh", fake + script, {"DNS_MANAGED_BY_POLICY": "true"})
        self.assertEqual(0, code, stdout + stderr)
        self.assertIn("-DnsManagedByPolicy", stdout)

    def test_shared_seeding_helper_policy_mode_stops_before_dns_apis(self):
        content = KV_HELPER.read_text(encoding="utf-8")
        # Replace network resolver only; execute all PE discovery and DNS ownership logic.
        marker = "$dnsZoneName = 'privatelink.vaultcore.azure.net'"
        mock = r"""
function Wait-KeyVaultPrivateDns {
  param($HostName, $ExpectedIp)
  if ($HostName -ne 'seed.vault.azure.net' -or $ExpectedIp -ne '10.2.0.4') { throw 'Wrong DNS validation target' }
  Write-Host 'DNS_LOOKUP_ONLY'
}
function az {
  $global:LASTEXITCODE = 0
  $call = $args -join ' '
  Write-Host "AZ:$call"
  if ($call -match 'private-dns|dns-zone-group') { throw 'DNS_CONTROL_PLANE_REACHED' }
  if ($call -match '^keyvault show') { return '{"id":"/subscriptions/sub/resourceGroups/seed/providers/Microsoft.KeyVault/vaults/seed"}' }
  if ($call -match '^network private-endpoint-connection list') {
    return '[{"privateLinkServiceConnectionState":{"status":"Approved"},"privateEndpoint":{"id":"/subscriptions/sub/resourceGroups/pe/providers/Microsoft.Network/privateEndpoints/seed"}}]'
  }
  if ($call -match '^network private-endpoint show') {
    return '{"subnet":{"id":"/subscriptions/sub/resourceGroups/network/providers/Microsoft.Network/virtualNetworks/vnet/subnets/pe"},"networkInterfaces":[{"id":"/subscriptions/sub/resourceGroups/pe/providers/Microsoft.Network/networkInterfaces/seed"}]}'
  }
  if ($call -match '^network nic show') { return '{"ipConfigurations":[{"privateIPAddress":"10.2.0.4"}]}' }
  if ($call -match '^network vnet show') { return '{"id":"/subscriptions/sub/resourceGroups/network/providers/Microsoft.Network/virtualNetworks/vnet"}' }
  throw "Unexpected mock call $call"
}
"""
        self.assertEqual(1, content.count(marker))
        content = content.replace(marker, mock + "\n" + marker)
        for central in (True, False):
            invocation = (
                "& {\n" + content + "\n} -VaultSubscription sub -VaultResourceGroup seed -VaultName seed "
                "-VnetSubscription sub -VnetResourceGroup network -VnetName vnet "
                "-DnsZoneSubscription other-sub -DnsZoneResourceGroup forbidden-hub"
                + (" -DnsManagedByPolicy" if central else "")
            )
            with self.subTest(central=central):
                code, stdout, stderr = self.run_shell("pwsh", invocation)
                if central:
                    self.assertEqual(0, code, stdout + stderr)
                    self.assertIn("DNS_LOOKUP_ONLY", stdout)
                    self.assertNotIn("AZ:network private-dns", stdout)
                    self.assertNotIn("dns-zone-group", stdout)
                    self.assertNotIn("other-sub", stdout)
                else:
                    self.assertNotEqual(0, code)
                    self.assertIn("DNS_CONTROL_PLANE_REACHED", stderr)

    def test_seeding_dns_wait_succeeds_or_reports_real_resolution_failure(self):
        content = KV_HELPER.read_text(encoding="utf-8")
        function = content[content.index("function Wait-KeyVaultPrivateDns"):content.index("$dnsZoneName =")]
        setup = """
$ErrorActionPreference = 'Stop'
function Clear-DnsClientCache {}
function Start-Sleep {}
function az { throw 'Resolver must not call Azure APIs' }
"""
        for expected, success in (("127.0.0.1", True), ("192.0.2.4", False)):
            with self.subTest(expected=expected):
                code, stdout, stderr = self.run_shell(
                    "pwsh", setup + function + f"\nWait-KeyVaultPrivateDns -HostName localhost -ExpectedIp {expected}"
                )
                if success:
                    self.assertEqual(0, code, stdout + stderr)
                    self.assertIn("resolves to approved private endpoint IP", stdout)
                else:
                    self.assertNotEqual(0, code)
                    self.assertIn("check 18/18", stdout)
                    self.assertIn("DNS/policy owner", stderr)
                    self.assertNotIn("resolves to approved private endpoint IP", stdout)


class BicepDnsOwnershipTests(unittest.TestCase):
    def test_foundry_zone_groups_honor_policy_but_endpoint_resources_do_not_depend_on_dns_mode(self):
        expectations = {
            FOUNDRY_PE: {
                "privateEndpointDns": "!centralDnsZoneByPolicyInHub && createPrivateEndpointsAIFactoryWay",
                "privateEndpointDnsAPIM": "!centralDnsZoneByPolicyInHub && apiManagementProvided && createPrivateEndpointsAIFactoryWay",
            },
            APIM_PE: {
                "privateEndpointDnsGroupAIF": "!centralDnsZoneByPolicyInHub",
                "privateEndpointDnsGroupAPIM": "!centralDnsZoneByPolicyInHub && !empty(apiManagementName)",
            },
        }
        for path, resources in expectations.items():
            content = path.read_text(encoding="utf-8")
            for name, condition in resources.items():
                with self.subTest(path=path.name, resource=name):
                    self.assertIn(
                        f"resource {name} 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if ({condition})",
                        content,
                    )
            for declaration in re.findall(r"(?m)^resource \w+ 'Microsoft.Network/privateEndpoints@[^']+' = .*", content):
                self.assertNotIn("centralDnsZoneByPolicyInHub", declaration)

    def test_foundry_routes_forward_dns_flag_and_foundation_does_not_create_policy_zones(self):
        for name in ("09-ai-foundry-2025-v2", "09-ai-foundry-2025-v3", "09-ai-foundry-2025-v4"):
            content = (BICEP / f"esml-genai-1/{name}.bicep").read_text(encoding="utf-8")
            self.assertIn("centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub", content)
        foundation = (BICEP / "esml-genai-1/01-foundation.bicep").read_text(encoding="utf-8")
        self.assertIn(
            "module createNewPrivateDnsZonesIfNotExists '../modules/createNewPrivateDnsZonesIfNotExists.bicep' = if (centralDnsZoneByPolicyInHub == false)",
            foundation,
        )


if __name__ == "__main__":
    unittest.main()
