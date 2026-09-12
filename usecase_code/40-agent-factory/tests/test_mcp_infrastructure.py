"""Offline source and compiled-ARM contracts; no Azure deployment or authentication."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
ENTRY = BICEP / "esml-genai-1" / "08-azure-mcp.bicep"
MODULE = BICEP / "modules" / "azureMcpServer.bicep"
READER_ROLE = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
REQUIRED_INPUTS = {
    "projectResourceGroup", "name", "infrastructureSubnetId",
    "privateEndpointSubnetId", "tenantId", "entraApiApplicationClientId",
    "containerImage", "allowedTools", "privateDnsZoneResourceId",
    "centralDnsZoneByPolicyInHub",
}
OUTPUTS = {
    "containerAppResourceId", "identityPrincipalId", "appIdentity",
    "managedEnvironmentResourceId", "defaultDomain", "staticIp", "mcpUrl",
    "privateEndpointResourceId", "readerRoleAssignmentResourceId",
    "readerRoleDefinitionResourceId", "deploymentInputs",
}


def resources(template):
    value = template["resources"]
    return list(value.values()) if isinstance(value, dict) else value


def resource_of_type(template, resource_type):
    matches = [r for r in resources(template) if r["type"] == resource_type]
    if len(matches) != 1:
        raise AssertionError(f"Expected one {resource_type}, found {len(matches)}")
    return matches[0]


def function_body(template, name):
    matches = [
        namespace["members"][name]["output"]["value"]
        for namespace in template["functions"]
        if name in namespace["members"]
    ]
    if len(matches) != 1:
        raise AssertionError(f"Expected one function {name}, found {len(matches)}")
    return matches[0]


class McpInfrastructureSourceTests(unittest.TestCase):
    def test_entry_and_module_scopes_and_shared_guards(self):
        entry = ENTRY.read_text(encoding="utf-8")
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn("targetScope = 'subscription'", entry)
        self.assertIn("targetScope = 'resourceGroup'", module)
        self.assertIn("scope: resourceGroup(projectResourceGroup)", entry)
        for guard in (
            "requireInfrastructureSubnetId", "requirePrivateEndpointSubnetId",
            "requirePinnedAzureMcpImage", "requirePrivateDnsZoneResourceId",
        ):
            self.assertIn(f"func {guard}(", module)
            self.assertIn(guard, entry)
        self.assertNotRegex(module, r"(?m)^\s*assert\s")

    def test_only_safe_existing_dns_module_is_reused(self):
        source = MODULE.read_text(encoding="utf-8")
        modules = re.findall(r"(?m)^module\s+\w+\s+'([^']+)'", source)
        self.assertEqual(["privateDns.bicep"], modules)
        self.assertNotIn("containerappsEnv.bicep", source)
        self.assertNotIn("containerapp.bicep", source)
        self.assertIn("if (!centralDnsZoneByPolicyInHub)", source)

    def test_subnet_and_tls_prerequisites_are_documented_in_place(self):
        source = MODULE.read_text(encoding="utf-8")
        for prerequisite in (
            "unused ACA", "Microsoft.App/environments", "at least /27",
            "nondelegated", "Entra incoming authentication remains enabled",
            "ACA terminates TLS", "NOT the public internet",
        ):
            self.assertIn(prerequisite, source)


class McpInfrastructureCompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        az = shutil.which("az")
        bicep = shutil.which("bicep")
        if az:
            command = [az, "bicep", "build"]
        elif bicep:
            command = [bicep, "build"]
        else:
            raise unittest.SkipTest("Existing Azure CLI/Bicep CLI required for compiled contracts")
        result = subprocess.run(
            command + ["--file", str(ENTRY), "--stdout"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=120, check=False,
        )
        if result.returncode:
            raise AssertionError(f"Bicep compilation failed:\n{result.stderr}")
        if re.search(r"\b(?:Warning|Error) (?:BCP\d+|[a-z-]+):", result.stderr):
            raise AssertionError(f"Bicep diagnostics must be resolved:\n{result.stderr}")
        cls.entry = json.loads(result.stdout)
        cls.deployment = resource_of_type(cls.entry, "Microsoft.Resources/deployments")
        cls.module = cls.deployment["properties"]["template"]
        cls.environment = resource_of_type(cls.module, "Microsoft.App/managedEnvironments")
        cls.app = resource_of_type(cls.module, "Microsoft.App/containerApps")
        cls.container = cls.app["properties"]["template"]["containers"][0]
        cls.endpoint = resource_of_type(cls.module, "Microsoft.Network/privateEndpoints")
        cls.dns = resource_of_type(cls.module, "Microsoft.Resources/deployments")

    def test_entry_targets_only_existing_project_group(self):
        self.assertIn("subscriptionDeploymentTemplate", self.entry["$schema"])
        self.assertEqual(1, len(resources(self.entry)))
        self.assertEqual("[parameters('projectResourceGroup')]", self.deployment["resourceGroup"])
        self.assertEqual("Incremental", self.deployment["properties"]["mode"])
        self.assertEqual(
            "[deployment().location]",
            self.entry["parameters"]["location"]["defaultValue"],
        )
        for name in REQUIRED_INPUTS:
            with self.subTest(parameter=name):
                self.assertNotIn("defaultValue", self.entry["parameters"][name])

    def test_exact_nonempty_tool_allowlist_at_both_scopes(self):
        for template in (self.entry, self.module):
            with self.subTest(scope=template["$schema"]):
                parameter = template["parameters"]["allowedTools"]
                self.assertEqual("array", parameter["type"])
                self.assertEqual(1, parameter["minLength"])
                self.assertEqual(1, parameter["maxLength"])
                definition = parameter["items"]["$ref"].rsplit("/", 1)[-1]
                self.assertEqual(
                    ["group_resource_list"],
                    template["definitions"][definition]["allowedValues"],
                )
                self.assertNotIn("defaultValue", parameter)

    def test_all_reference_validation_runs_before_rg_deployment(self):
        params = self.deployment["properties"]["parameters"]
        for name, guard in (
            ("infrastructureSubnetId", "requireInfrastructureSubnetId"),
            ("privateEndpointSubnetId", "requirePrivateEndpointSubnetId"),
            ("containerImage", "requirePinnedAzureMcpImage"),
            ("privateDnsZoneResourceId", "requirePrivateDnsZoneResourceId"),
        ):
            with self.subTest(parameter=name):
                self.assertIn(guard, params[name]["value"])
                self.assertIn(f"parameters('{name}')", params[name]["value"])
                for template in (self.entry, self.module):
                    self.assertIn("fail(", function_body(template, guard))

    def test_distinct_subnet_ids_are_case_insensitive_and_type_checked(self):
        for template in (self.entry, self.module):
            body = function_body(template, "requirePrivateEndpointSubnetId")
            self.assertIn("isSubnetResourceId(parameters('id'))", body)
            self.assertIn(
                "not(equals(toLower(parameters('id')), toLower(parameters('infrastructureId'))))",
                body,
            )
            validator = function_body(template, "isSubnetResourceId")
            self.assertIn("equals(length(split(parameters('id'), '/')), 11)", validator)
            for segment in (
                "subscriptions", "resourcegroups", "providers",
                "microsoft.network", "virtualnetworks", "subnets",
            ):
                self.assertIn(f"'{segment}'", validator)
            self.assertIn("tryGet(", validator)
            dns_validator = function_body(template, "requirePrivateDnsZoneResourceId")
            self.assertIn("equals(length(split(parameters('id'), '/')), 9)", dns_validator)
            self.assertIn("'privatednszones'", dns_validator)

    def test_image_is_official_digest_only_not_merely_a_nonempty_string(self):
        for template in (self.entry, self.module):
            self.assertNotIn("defaultValue", template["parameters"]["containerImage"])
            body = function_body(template, "requirePinnedAzureMcpImage")
            self.assertIn("equals(parameters('image'), format(", body)
            self.assertIn("mcr.microsoft.com/azure-sdk/azure-mcp@sha256:{0}", body)
            self.assertIn("isSha256Digest(", body)
            digest = function_body(template, "isSha256Digest")
            self.assertIn("equals(length(parameters('digest')), 64)", digest)
            self.assertIn("not(contains('0123456789abcdef', substring(", digest)
        self.assertEqual("[variables('validatedContainerImage')]", self.container["image"])

    def test_internal_environment_disables_public_access_on_first_create(self):
        props = self.environment["properties"]
        self.assertEqual("2025-07-01", self.environment["apiVersion"])
        self.assertIs(True, props["vnetConfiguration"]["internal"])
        self.assertEqual("Disabled", props["publicNetworkAccess"])
        self.assertEqual(
            "[variables('validatedInfrastructureSubnetId')]",
            props["vnetConfiguration"]["infrastructureSubnetId"],
        )
        self.assertEqual(
            [{"name": "Consumption", "workloadProfileType": "Consumption"}],
            props["workloadProfiles"],
        )
        self.assertNotIn("appLogsConfiguration", props)
        self.assertNotIn("condition", self.environment)

    def test_ingress_is_tls_only_and_single_replica(self):
        props = self.app["properties"]
        self.assertEqual("Consumption", props["workloadProfileName"])
        self.assertIn("Microsoft.App/managedEnvironments", props["environmentId"])
        self.assertEqual("Single", props["configuration"]["activeRevisionsMode"])
        self.assertEqual({
            "external": True, "allowInsecure": False,
            "targetPort": 8080, "transport": "http",
        }, props["configuration"]["ingress"])
        self.assertEqual({"minReplicas": 1, "maxReplicas": 1}, props["template"]["scale"])
        self.assertEqual(1, len(props["template"]["containers"]))
        self.assertEqual({"cpu": "[json('0.5')]", "memory": "1Gi"}, self.container["resources"])

    def test_image_entrypoint_and_explicit_readonly_tools_are_preserved(self):
        self.assertEqual([], self.container["command"])
        self.assertEqual("[variables('serverArgs')]", self.container["args"])
        args = self.module["variables"]["serverArgs"]
        self.assertIn(
            "createArray('--transport', 'http', '--outgoing-auth-strategy', "
            "'UseHostingEnvironmentIdentity', '--mode', 'all', '--read-only')",
            args,
        )
        self.assertIn(
            "flatten(map(parameters('allowedTools'), lambda('tool', "
            "createArray('--tool', lambdaVariables('tool')))))",
            args,
        )
        for unexpected in ("--namespace", "--debug", "--dangerously-disable-http-incoming-auth"):
            self.assertNotIn(unexpected, args)

    def test_separate_inbound_entra_and_outbound_system_identity(self):
        self.assertEqual({"type": "SystemAssigned"}, self.app["identity"])
        env = {item["name"]: item["value"] for item in self.container["env"]}
        self.assertEqual({
            "AZURE_TOKEN_CREDENTIALS": "managedidentitycredential",
            "AZURE_MCP_INCLUDE_PRODUCTION_CREDENTIALS": "true",
            "AZURE_MCP_COLLECT_TELEMETRY": "false",
            "AzureAd__Instance": "[environment().authentication.loginEndpoint]",
            "AzureAd__TenantId": "[parameters('tenantId')]",
            "AzureAd__ClientId": "[parameters('entraApiApplicationClientId')]",
            "ASPNETCORE_ENVIRONMENT": "Production",
            "DOTNET_ENVIRONMENT": "Production",
            "ASPNETCORE_URLS": "http://0.0.0.0:8080",
            "AZURE_MCP_DANGEROUSLY_DISABLE_HTTPS_REDIRECTION": "true",
            "Logging__LogLevel__Default": "Warning",
            "Logging__LogLevel__Azure": "Warning",
            "Logging__LogLevel__Microsoft": "Warning",
        }, env)

    def test_tcp_probes_do_not_bypass_http_authentication(self):
        probes = {probe["type"]: probe for probe in self.container["probes"]}
        self.assertEqual({"Startup", "Readiness", "Liveness"}, set(probes))
        for name, probe in probes.items():
            with self.subTest(probe=name):
                self.assertEqual({"port": 8080}, probe["tcpSocket"])
                self.assertNotIn("httpGet", probe)
                self.assertNotIn("httpHeaders", probe)
                self.assertGreaterEqual(probe["initialDelaySeconds"], 10)
                self.assertGreaterEqual(probe["periodSeconds"], 5)
                self.assertGreaterEqual(probe["failureThreshold"], 3)

    def test_only_role_is_reader_at_current_project_rg(self):
        role = resource_of_type(self.module, "Microsoft.Authorization/roleAssignments")
        self.assertEqual(
            f"[subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '{READER_ROLE}')]",
            self.module["variables"]["readerRoleDefinitionId"],
        )
        self.assertEqual("[variables('readerRoleDefinitionId')]", role["properties"]["roleDefinitionId"])
        self.assertIn("reference('app'", role["properties"]["principalId"])
        self.assertTrue(role["properties"]["principalId"].endswith(".identity.principalId]"))
        self.assertEqual("ServicePrincipal", role["properties"]["principalType"])
        self.assertNotIn("scope", role)
        self.assertNotIn("subscriptionId", role)
        self.assertNotIn("resourceGroup", role)
        self.assertIn("resourceGroup().id", role["name"])
        self.assertIn("app", role["dependsOn"])

    def test_endpoint_uses_separate_subnet_and_environment_group(self):
        props = self.endpoint["properties"]
        self.assertEqual(
            {"id": "[variables('validatedPrivateEndpointSubnetId')]"},
            props["subnet"],
        )
        connections = props["privateLinkServiceConnections"]
        self.assertEqual(1, len(connections))
        self.assertEqual(["managedEnvironments"], connections[0]["properties"]["groupIds"])
        self.assertIn("Microsoft.App/managedEnvironments", connections[0]["properties"]["privateLinkServiceId"])
        self.assertNotIn("privateLinkServiceConnectionState", connections[0]["properties"])
        self.assertNotIn("condition", self.endpoint)

    def test_dns_policy_exclusively_owns_group_when_enabled(self):
        self.assertEqual("[not(parameters('centralDnsZoneByPolicyInHub'))]", self.dns["condition"])
        self.assertIn("privateEndpoint", self.dns["dependsOn"])
        params = self.dns["properties"]["parameters"]
        self.assertEqual(
            "[variables('validatedPrivateDnsZoneResourceId')]",
            params["privateLinksDnsZones"]["value"]["azurecontainerapps"]["id"],
        )
        self.assertEqual("azurecontainerapps", params["dnsConfig"]["value"][0]["type"])
        dns_template = self.dns["properties"]["template"]
        self.assertEqual(
            ["Microsoft.Network/privateEndpoints/privateDnsZoneGroups"],
            [r["type"] for r in resources(dns_template)],
        )
        group = resources(dns_template)[0]
        self.assertIn(
            "parameters('privateLinksDnsZones')",
            group["properties"]["privateDnsZoneConfigs"][0]["properties"]["privateDnsZoneId"],
        )

    def test_no_shared_identity_secrets_or_unrelated_resource_writes(self):
        self.assertCountEqual([
            "Microsoft.App/managedEnvironments", "Microsoft.App/containerApps",
            "Microsoft.Authorization/roleAssignments", "Microsoft.Network/privateEndpoints",
            "Microsoft.Resources/deployments",
        ], [r["type"] for r in resources(self.module)])
        raw = json.dumps(self.module)
        for forbidden in (
            "userAssignedIdentities", "Microsoft.ManagedIdentity",
            "Microsoft.CognitiveServices", "Microsoft.ContainerRegistry",
            "Microsoft.Network/virtualNetworks/subnets\"",
            "Microsoft.Network/privateDnsZones\"",
            "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "secretRef",
            "listKeys(", "sharedKey", "logAnalyticsConfiguration",
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "DANGEROUSLY_ENABLE_FORWARDED_HEADERS", "FORWARDEDHEADERS_ENABLED",
            "dangerously-disable-http-incoming-auth",
            "dangerously-write-support-logs", "DataActions",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, raw)
        self.assertNotIn("secrets", self.app["properties"]["configuration"])
        self.assertNotIn("registries", self.app["properties"]["configuration"])

    def test_outputs_include_canonical_mcp_url_and_reproducible_inputs(self):
        self.assertEqual(OUTPUTS, set(self.entry["outputs"]))
        self.assertEqual(OUTPUTS, set(self.module["outputs"]))
        self.assertEqual(
            "[format('https://{0}/mcp', reference('app').configuration.ingress.fqdn)]",
            self.module["outputs"]["mcpUrl"]["value"],
        )
        for output, member in (("defaultDomain", "defaultDomain"), ("staticIp", "staticIp")):
            self.assertEqual(
                f"[reference('managedEnvironment').{member}]",
                self.module["outputs"][output]["value"],
            )
        inputs = self.module["outputs"]["deploymentInputs"]["value"]
        self.assertTrue(REQUIRED_INPUTS <= set(inputs))
        self.assertEqual("[resourceGroup().id]", inputs["projectResourceGroupId"])
        self.assertEqual("[subscription().subscriptionId]", inputs["subscriptionId"])


if __name__ == "__main__":
    unittest.main()
